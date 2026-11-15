"""Response headers applied to every reply."""

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class ApiHeadersMiddleware:
    """Marks every response as private and non-cacheable.

    The frontend reaches this API through a Vercel rewrite, and Vercel's CDN may
    cache proxied responses. Financial data must never be cached or shared, so
    `no-store` is set here rather than trusting any proxy default.

    Written as plain ASGI (not BaseHTTPMiddleware) so it cannot interfere with
    streaming responses or background work later on.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
                headers["X-Content-Type-Options"] = "nosniff"
                headers["Referrer-Policy"] = "no-referrer"
            await send(message)

        await self.app(scope, receive, send_with_headers)