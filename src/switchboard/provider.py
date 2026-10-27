"""Small provider boundary and HTTP adapter for non-streaming completions."""

from typing import Protocol

import httpx
from pydantic import ValidationError

from switchboard.contracts import ChatCompletionRequest, ChatCompletionResponse
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

            if response.status_code == 429:
                raise ProviderRateLimitError
            if 400 <= response.status_code < 500:
                raise ProviderRejectedRequestError
            if response.status_code >= 500:
                raise ProviderServerError
            if not 200 <= response.status_code < 300:
                raise InvalidProviderResponseError

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
