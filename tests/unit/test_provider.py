"""Unit tests for provider-adapter exception and cancellation boundaries."""

import asyncio

import httpx
import pytest

from switchboard.contracts import ChatCompletionRequest, ChatMessage
from switchboard.provider import HttpxMockProvider


@pytest.fixture
def anyio_backend() -> str:
    """Run cancellation semantics on the asyncio backend used by Uvicorn."""
    return "asyncio"


@pytest.mark.anyio
async def test_cancellation_is_not_translated_into_provider_failure() -> None:
    """Task cancellation must escape the adapter so upstream work can stop."""

    async def cancel(_: httpx.Request) -> httpx.Response:
        raise asyncio.CancelledError

    request = ChatCompletionRequest(
        model="mock-v1",
        messages=[ChatMessage(role="user", content="cancel this request")],
    )
    async with httpx.AsyncClient(
        base_url="http://mock-provider",
        transport=httpx.MockTransport(cancel),
    ) as client:
        provider = HttpxMockProvider(client)

        with pytest.raises(asyncio.CancelledError):
            await provider.complete(request, request_id="cancellation-test")
