"""Request-correlation identifiers and ASGI propagation middleware."""

import re
import uuid

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "x-request-id"
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def new_request_id() -> str:
    """Create an opaque request ID without host, process, or user information."""
    return f"req_{uuid.uuid4().hex}"


def resolve_request_id(candidate: str | None) -> str:
    """Accept one safe incoming ID or replace an absent/unsafe value."""
    if candidate is not None and REQUEST_ID_PATTERN.fullmatch(candidate):
        return candidate
    return new_request_id()


class RequestIdMiddleware:
    """Store one request ID in ASGI state and expose it on every HTTP response."""

    def __init__(self, application: ASGIApp) -> None:
        self.application = application

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.application(scope, receive, send)
            return

        headers = Headers(scope=scope)
        request_id = resolve_request_id(headers.get(REQUEST_ID_HEADER))
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[REQUEST_ID_HEADER] = request_id
            await send(message)

        await self.application(scope, receive, send_with_request_id)
