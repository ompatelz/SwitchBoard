"""Small Qdrant REST boundary with mandatory server-derived isolation filters."""

import asyncio
import hashlib
import math
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from switchboard.embedding_model import MODEL_DIMENSION
from switchboard.semantic_policy import SemanticScope

COLLECTION = "switchboard_semantic_v1"
_KEYWORD_FIELDS = (
    "tenant_digest",
    "model",
    "provider_policy",
    "embedding_model_version",
    "cache_schema_version",
    "semantic_policy_version",
    "subject_digest",
)


class QdrantUnavailable(Exception):
    """Vector storage cannot provide a trustworthy candidate set."""


@dataclass(frozen=True)
class VectorCandidate:
    point_id: str
    score: float
    response_ref: str


def tenant_digest(scope: SemanticScope) -> str:
    return hashlib.sha256(scope.tenant_id.encode("utf-8")).hexdigest()


def subject_digest(subject: str) -> str:
    return hashlib.sha256(subject.encode("utf-8")).hexdigest()


def _metadata(scope: SemanticScope, subject: str) -> dict[str, str | int]:
    return {
        "tenant_digest": tenant_digest(scope),
        "model": scope.model,
        "provider_policy": scope.provider_policy,
        "embedding_model_version": scope.embedding_model_version,
        "cache_schema_version": scope.cache_schema_version,
        "semantic_policy_version": scope.semantic_policy_version,
        "subject_digest": subject_digest(subject),
    }


def _vector_is_valid(vector: list[float]) -> bool:
    return (
        len(vector) == MODEL_DIMENSION
        and all(math.isfinite(value) for value in vector)
        and math.isclose(math.sqrt(math.fsum(value * value for value in vector)), 1.0, abs_tol=1e-4)
    )


class QdrantRepository:
    """Owns one collection; no caller may supply a query filter or tenant value."""

    def __init__(self, client: httpx.AsyncClient, *, collection: str = COLLECTION) -> None:
        if not collection or not all(char.isalnum() or char in "_-" for char in collection):
            raise ValueError("invalid Qdrant collection name")
        self.client = client
        self.collection = collection
        self._initialized = False
        self._initialization_lock = asyncio.Lock()

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = await self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            self._initialized = False
            raise QdrantUnavailable from exc

    async def ensure_ready(self) -> None:
        if self._initialized:
            return
        async with self._initialization_lock:
            if not self._initialized:
                await self.ensure_collection()
                self._initialized = True

    async def ensure_collection(self) -> None:
        path = f"/collections/{self.collection}"
        try:
            current = await self.client.get(path)
            if current.status_code == 404:
                await self._request(
                    "PUT", path, json={"vectors": {"size": MODEL_DIMENSION, "distance": "Cosine"}}
                )
                current = await self._request("GET", path)
            else:
                current.raise_for_status()
            result = current.json()["result"]
            vectors = result["config"]["params"]["vectors"]
            if vectors != {"size": MODEL_DIMENSION, "distance": "Cosine"}:
                raise QdrantUnavailable("incompatible Qdrant vector schema")
            indexed = result.get("payload_schema", {})
            for field in _KEYWORD_FIELDS:
                if field not in indexed:
                    field_schema: str | dict[str, str | bool] = "keyword"
                    if field == "tenant_digest":
                        field_schema = {"type": "keyword", "is_tenant": True}
                    await self._request(
                        "PUT",
                        f"{path}/index",
                        params={"wait": "true"},
                        json={"field_name": field, "field_schema": field_schema},
                    )
                elif indexed[field].get("data_type") != "keyword":
                    raise QdrantUnavailable("incompatible Qdrant payload index")
            if "expires_at" not in indexed:
                await self._request(
                    "PUT",
                    f"{path}/index",
                    params={"wait": "true"},
                    json={"field_name": "expires_at", "field_schema": "integer"},
                )
            elif indexed["expires_at"].get("data_type") != "integer":
                raise QdrantUnavailable("incompatible Qdrant expiry index")
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
            raise QdrantUnavailable from exc

    async def search(
        self,
        scope: SemanticScope,
        subject: str,
        vector: list[float],
        *,
        limit: int,
        now: int,
    ) -> tuple[VectorCandidate, ...]:
        if not _vector_is_valid(vector) or not 1 <= limit <= 20:
            raise ValueError("invalid vector query bounds")
        await self.ensure_ready()
        metadata = _metadata(scope, subject)
        conditions = [{"key": key, "match": {"value": value}} for key, value in metadata.items()]
        conditions.append({"key": "expires_at", "range": {"gt": now}})
        response = await self._request(
            "POST",
            f"/collections/{self.collection}/points/query",
            json={
                "query": vector,
                "filter": {"must": conditions},
                "limit": limit,
                "with_payload": True,
                "with_vector": False,
            },
        )
        try:
            points = response.json()["result"]["points"]
            candidates: list[VectorCandidate] = []
            for point in points:
                payload = point["payload"]
                if any(payload.get(key) != value for key, value in metadata.items()):
                    raise ValueError("Qdrant returned incompatible metadata")
                if not isinstance(payload.get("expires_at"), int) or payload["expires_at"] <= now:
                    raise ValueError("Qdrant returned an expired point")
                score = float(point["score"])
                if not math.isfinite(score) or not -1.000001 <= score <= 1.000001:
                    raise ValueError("Qdrant returned an invalid score")
                candidates.append(
                    VectorCandidate(
                        point_id=str(point["id"]),
                        score=score,
                        response_ref=str(payload["response_ref"]),
                    )
                )
            return tuple(
                sorted(candidates, key=lambda candidate: (-candidate.score, candidate.point_id))
            )
        except (ValueError, TypeError, KeyError, AttributeError) as exc:
            raise QdrantUnavailable from exc

    async def insert(
        self,
        scope: SemanticScope,
        subject: str,
        vector: list[float],
        *,
        response_ref: str,
        expires_at: int,
    ) -> str:
        if not _vector_is_valid(vector) or expires_at <= 0:
            raise ValueError("invalid vector insert")
        await self.ensure_ready()
        point_id = str(uuid.uuid4())
        await self._request(
            "PUT",
            f"/collections/{self.collection}/points",
            params={"wait": "true"},
            json={
                "points": [
                    {
                        "id": point_id,
                        "vector": vector,
                        "payload": {
                            **_metadata(scope, subject),
                            "response_ref": response_ref,
                            "expires_at": expires_at,
                        },
                    }
                ]
            },
        )
        return point_id

    async def prune_expired(self, *, now: int) -> None:
        await self.ensure_ready()
        await self._request(
            "POST",
            f"/collections/{self.collection}/points/delete",
            params={"wait": "true"},
            json={"filter": {"must": [{"key": "expires_at", "range": {"lte": now}}]}},
        )
