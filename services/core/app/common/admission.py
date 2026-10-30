"""Queue business requests before synchronous dependencies consume worker threads."""

import asyncio

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from app.common.errors import error_response


class DatabaseAdmissionMiddleware:
    def __init__(self, app: ASGIApp, *, capacity: int, timeout: float):
        if capacity < 1 or timeout <= 0:
            raise ValueError("Admission capacity and timeout must be positive")
        self.app = app
        self.slots = asyncio.BoundedSemaphore(capacity)
        self.timeout = timeout

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not scope["path"].startswith(("/api/", "/internal/")):
            await self.app(scope, receive, send)
            return
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=self.timeout)
        except TimeoutError:
            response = error_response(
                Request(scope),
                503,
                "Hệ thống đang bận. Vui lòng chờ một chút rồi thử lại.",
                {"Retry-After": "1"},
            )
            await response(scope, receive, send)
            return
        try:
            # Hold through dependency cleanup, so its connection is returned
            # before the next request enters the synchronous worker pool.
            await self.app(scope, receive, send)
        finally:
            self.slots.release()
