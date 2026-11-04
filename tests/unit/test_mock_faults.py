"""Mock failure scenarios used by Phase 2A fault tests."""

from typing import cast

import pytest
from fastapi.testclient import TestClient

from switchboard.mock_provider import MockFailureScenario, create_app

REQUEST = {"model": "mock-v1", "messages": [{"role": "user", "content": "test"}]}


@pytest.mark.parametrize(
    ("scenario", "status"),
    [("rate_limit", 429), ("server_500", 500), ("server_503", 503), ("invalid", 200)],
)
def test_deterministic_fault_scenario(scenario: str, status: int) -> None:
    with TestClient(create_app(failure_scenario=cast(MockFailureScenario, scenario))) as client:
        response = client.post("/v1/chat/completions", json=REQUEST)
    assert response.status_code == status
    if scenario == "rate_limit":
        assert response.headers["retry-after"] == "1"
    if scenario == "invalid":
        assert response.json() == {"invalid": True}
