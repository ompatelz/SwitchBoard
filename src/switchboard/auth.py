"""Small fail-closed development API-key boundary."""

import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class TenantIdentity:
    """Validated tenant identity carried by FastAPI dependency injection."""

    tenant_id: str


class ApiKeyAuthenticator:
    """Match high-entropy bearer keys against configured SHA-256 digests."""

    def __init__(self, key_hashes: dict[str, str], revoked_hashes: set[str]) -> None:
        self._key_hashes = dict(key_hashes)
        self._revoked_hashes = set(revoked_hashes)

    def authenticate(self, authorization: str | None) -> TenantIdentity | None:
        if authorization is None or not authorization.startswith("Bearer "):
            return None
        key = authorization[7:]
        if not key or len(key) > 256:
            return None
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        if any(hmac.compare_digest(digest, revoked) for revoked in self._revoked_hashes):
            return None
        matched: str | None = None
        for tenant_id, expected in self._key_hashes.items():
            if hmac.compare_digest(digest, expected):
                matched = tenant_id
        return TenantIdentity(matched) if matched is not None else None
