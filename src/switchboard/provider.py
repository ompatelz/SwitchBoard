"""Small provider boundary and HTTP adapter for Chat Completions."""

from collections.abc import AsyncGenerator, AsyncIterator
from typing import Literal, Protocol

import httpx
from pydantic import ValidationError

from switchboard.contracts import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from switchboard.request_ids import REQUEST_ID_HEADER


class ProviderError(Exception):
    """Base for expected provider-boundary failures."""


class ProviderConnectionError(ProviderError):
    """The provider could not be reached."""


class ProviderTimeoutError(ProviderError):
    """A configured provider timeout elapsed."""


class ProviderRejectedRequestError(ProviderError):
    """The provider rejected a request that passed the gateway contract."""


class ProviderRateLimitError(ProviderError):
    """The provider reported rate limiting."""


class ProviderServerError(ProviderError):
    """The provider reported a server-side failure."""


class InvalidProviderResponseError(ProviderError):
    """The provider response did not match the declared contract."""


type StreamDone = Literal["[DONE]"]
type ChatStreamEvent = ChatCompletionChunk | StreamDone


class ChatProviderStream(Protocol):
    """Opened upstream stream whose response lifetime must be closed by its consumer."""

    def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        """Yield validated chunks followed by the done sentinel."""
        ...

    async def aclose(self) -> None:
        """Release the upstream response and its pooled connection."""
        ...


class ChatProvider(Protocol):
    """Minimal behavior the gateway needs from one completion provider."""

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str,
    ) -> ChatCompletionResponse:
        """Return one validated non-streaming completion."""
        ...

    async def open_stream(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str,
    ) -> ChatProviderStream:
        """Open and preflight one validated streaming completion."""
        ...


def _translate_status(response: httpx.Response) -> None:
    """Raise one stable provider-boundary exception for a non-success status."""
    if response.status_code == 429:
        raise ProviderRateLimitError
    if 400 <= response.status_code < 500:
        raise ProviderRejectedRequestError
    if response.status_code >= 500:
        raise ProviderServerError
    if not 200 <= response.status_code < 300:
        raise InvalidProviderResponseError


def _validate_stream_data(data: str) -> ChatStreamEvent:
    """Validate one upstream SSE data value without accepting extension events."""
    if data == "[DONE]":
        return "[DONE]"
    try:
        return ChatCompletionChunk.model_validate_json(data)
    except (ValueError, ValidationError) as exc:
        raise InvalidProviderResponseError from exc


async def _iter_sse_data(response: httpx.Response) -> AsyncIterator[str]:
    """Reassemble SSE events even when network chunks split lines or frames."""
    data_lines: list[str] = []
    async for line in response.aiter_lines():
        if line == "":
            if data_lines:
                yield "\n".join(data_lines)
                data_lines.clear()
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            data_lines.append(line[5:].lstrip(" "))
            continue
        raise InvalidProviderResponseError
    if data_lines:
        raise InvalidProviderResponseError


async def _iter_validated_events(response: httpx.Response) -> AsyncGenerator[ChatStreamEvent]:
    """Translate mid-stream transport failures and validate every SSE data event."""
    try:
        async for data in _iter_sse_data(response):
            yield _validate_stream_data(data)
    except httpx.TimeoutException as exc:
        raise ProviderTimeoutError from exc
    except httpx.RequestError as exc:
        raise ProviderConnectionError from exc


class HttpxProviderStream:
    """Opened HTTPX response plus its prefetched first validated event."""

    def __init__(
        self,
        response: httpx.Response,
        events: AsyncGenerator[ChatStreamEvent],
        first_event: ChatStreamEvent,
    ) -> None:
        self.response = response
        self.events = events
        self.first_event = first_event
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[ChatStreamEvent]:
        yield self.first_event
        if self.first_event == "[DONE]":
            return
        async for event in self.events:
            yield event
            if event == "[DONE]":
                return
        raise InvalidProviderResponseError

    async def aclose(self) -> None:
        if not self.closed:
            self.closed = True
            await self.events.aclose()
            await self.response.aclose()


class HttpxMockProvider:
    """Call the deterministic mock provider using a borrowed HTTPX client."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def complete(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str,
    ) -> ChatCompletionResponse:
        """Forward a request and translate transport/status/schema failures."""
        response: httpx.Response | None = None
        try:
            response = await self.client.post(
                "/v1/chat/completions",
                json=request.model_dump(mode="json"),
                headers={REQUEST_ID_HEADER: request_id},
            )

            _translate_status(response)

            try:
                return ChatCompletionResponse.model_validate(response.json())
            except (ValueError, ValidationError) as exc:
                raise InvalidProviderResponseError from exc
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError from exc
        except httpx.RequestError as exc:
            raise ProviderConnectionError from exc
        finally:
            if response is not None:
                await response.aclose()

    async def open_stream(
        self,
        request: ChatCompletionRequest,
        *,
        request_id: str,
    ) -> ChatProviderStream:
        """Open upstream streaming and validate its status and first SSE event."""
        response: httpx.Response | None = None
        try:
            upstream_request = self.client.build_request(
                "POST",
                "/v1/chat/completions",
                json=request.model_dump(mode="json"),
                headers={REQUEST_ID_HEADER: request_id},
            )
            response = await self.client.send(upstream_request, stream=True)
            _translate_status(response)
            content_type = response.headers.get("content-type", "")
            if not content_type.lower().startswith("text/event-stream"):
                raise InvalidProviderResponseError

            events = _iter_validated_events(response)
            try:
                first_event = await anext(events)
            except StopAsyncIteration as exc:
                raise InvalidProviderResponseError from exc
            return HttpxProviderStream(response, events, first_event)
        except httpx.TimeoutException as exc:
            if response is not None:
                await response.aclose()
            raise ProviderTimeoutError from exc
        except httpx.RequestError as exc:
            if response is not None:
                await response.aclose()
            raise ProviderConnectionError from exc
        except ProviderError:
            if response is not None:
                await response.aclose()
            raise
