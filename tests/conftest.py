"""Isolate ordinary tests from external Redis and production credentials."""

import hashlib
import json

import pytest

TEST_API_KEY = "switchboard-test-only-key-0123456789abcdef"


class EmptyRedis:
    """A no-hit cache stub for existing gateway contract tests."""

    async def get(self, name: str) -> bytes | None:
        return None

    async def set(self, name: str, value: bytes, *, ex: int) -> None:
        pass

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


@pytest.fixture(autouse=True)
def local_gateway_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    digest = hashlib.sha256(TEST_API_KEY.encode()).hexdigest()
    monkeypatch.setenv("SWITCHBOARD_TENANT_KEY_HASHES_JSON", json.dumps({"test": digest}))
    monkeypatch.setattr("switchboard.gateway.redis.from_url", lambda *args, **kwargs: EmptyRedis())
