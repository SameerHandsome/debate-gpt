"""Per-request logging middleware.

Generates a UUID4 `request_id`, sets it on the response as
`X-Request-ID`, times the request, and uses `logger.contextualize` so
all log lines emitted from within the request (including from asyncpg,
httpx, and FastAPI internals) carry the `request_id` automatically.

Per PRD §11.2.
"""
from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from .logging import logger


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        start = time.perf_counter()
        with logger.contextualize(request_id=request_id, trace_id="-", session_id="-"):
            try:
                response = await call_next(request)
                status_code = response.status_code
            except Exception as exc:  # noqa: BLE001
                latency_ms = (time.perf_counter() - start) * 1000
                logger.exception(
                    "request method={} path={} status=500 latency_ms={:.1f} "
                    "client={} error={!r}",
                    request.method,
                    request.url.path,
                    latency_ms,
                    request.client.host if request.client else "-",
                    exc,
                )
                # Re-raise so FastAPI's exception handlers can respond.
                raise
            latency_ms = (time.perf_counter() - start) * 1000
            client_ip = request.client.host if request.client else "-"
            logger.info(
                "request method={} path={} status={} latency_ms={:.1f} client={}",
                request.method,
                request.url.path,
                status_code,
                latency_ms,
                client_ip,
            )
        response.headers["X-Request-ID"] = request_id
        return response


__all__ = ["RequestLoggingMiddleware"]
