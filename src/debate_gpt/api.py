"""FastAPI surface for Debate-GPT (Day 3).

Six routes (PRD §5.1 + §11.4):

  POST   /debate/start           create session, kick background task
  GET    /debate/{id}/stream     SSE — poll Upstash Redis Stream
  GET    /debate/{id}/result     full transcript + scores (Postgres)
  GET    /debates?page=N         paginated list (20 per page)
  DELETE /debate/{id}            cascade-delete from DB + Redis
  GET    /health                 per-dependency status (200 or 503)

`create_app()` is the factory uvicorn imports when started with
`uvicorn debate_gpt.api:create_app --factory`.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field

from . import db, redis_stream
from .observability.health import router as health_router
from .observability.logging import (
    configure_logging,
    logger,
    start_loki_worker,
    stop_loki_worker,
)
from .observability.middleware import RequestLoggingMiddleware
from .runtime import run_debate_streaming

# Configure logging at import time so the very first log line is shaped
# correctly (FastAPI logs from uvicorn get intercepted here).
configure_logging()


# ---------- Response helper ----------

class DateTimeJSONResponse(JSONResponse):
    """JSONResponse that serializes datetime (and other non-JSON-native)
    values via `str()`, mirroring `json.dumps(..., default=str)`.

    Plain `JSONResponse` does not accept a `default=` kwarg — passing one
    raises `TypeError: JSONResponse.__init__() got an unexpected keyword
    argument 'default'`. This subclass overrides `render()` instead.
    """

    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=str).encode("utf-8")


# ---------- Request / response models ----------

class StartDebateRequest(BaseModel):
    topic: str = Field(min_length=3, max_length=500)
    max_rounds: int | None = Field(default=None, ge=2, le=5)


class StartDebateResponse(BaseModel):
    session_id: str
    status: str = "pending"


# ---------- Lifespan ----------

@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start the Loki async worker (if enabled) on startup; stop on shutdown."""
    await start_loki_worker()
    logger.info("app startup complete")
    try:
        yield
    finally:
        await stop_loki_worker()
        try:
            await db.close_pool()
        except Exception as exc:  # noqa: BLE001
            logger.warning("error closing db pool: {}", exc)
        logger.info("app shutdown complete")


# ---------- App factory ----------

def create_app() -> FastAPI:
    app = FastAPI(
        title="Debate-GPT",
        version="0.1.0",
        lifespan=_lifespan,
    )

    # CORS — only the configured origins; the React frontend will be
    # served from one of these.
    cors_origins_raw = os.getenv("CORS_ORIGINS", "*").strip()
    if cors_origins_raw == "*":
        cors_origins: list[str] = ["*"]
    else:
        cors_origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Request logging (X-Request-ID + structured log line per request).
    app.add_middleware(RequestLoggingMiddleware)

    # Health route.
    app.include_router(health_router)

    # ---------- POST /debate/start ----------

    @app.post("/debate/start", status_code=201)
    async def start_debate(
        body: StartDebateRequest,
        background_tasks: BackgroundTasks,
    ) -> JSONResponse:
        # Server-side clamp on rounds (PRD §13 risk). If the client
        # doesn't specify, fall back to MAX_ROUNDS env var (default 3).
        if body.max_rounds is None:
            body.max_rounds = int(os.getenv("MAX_ROUNDS", "3"))

        session_id = uuid.uuid4()
        topic = body.topic.strip()
        if not topic:
            raise HTTPException(status_code=422, detail="topic must not be empty")

        # Pre-create the DB row with a stable id so /debate/{id}/result
        # can be polled even before the background task has run.
        try:
            await db.create_debate(
                topic=topic,
                position_pro=f"For: {topic}",
                position_con=f"Against: {topic}",
                debate_id=session_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("start_debate: failed to insert debate row: {}", exc)
            raise HTTPException(status_code=503, detail="database unavailable") from exc

        background_tasks.add_task(
            run_debate_streaming, session_id, topic, body.max_rounds,
        )
        logger.info(
            "debate started session={} topic={!r} rounds={}",
            session_id, topic, body.max_rounds,
        )
        return JSONResponse(
            status_code=201,
            content={"session_id": str(session_id), "status": "pending"},
        )

    # ---------- GET /debate/{id}/stream ----------

    @app.get("/debate/{session_id}/stream")
    async def stream_debate(
        session_id: uuid.UUID,
        request: Request,
    ) -> StreamingResponse:
        last_event_id = request.headers.get("Last-Event-ID", "-")

        async def gen() -> AsyncIterator[bytes]:
            cursor = "-" if last_event_id in ("", "-") else f"({last_event_id}"
            sent_verdict = False
            while True:
                if await request.is_disconnected():
                    break
                try:
                    entries = await asyncio.to_thread(
                        redis_stream.xrange, str(session_id), cursor
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("sse xrange failed: {}", exc)
                    entries = []

                for entry in entries:
                    payload = entry["fields"]
                    data = {
                        "event": payload.get("event", "?"),
                        "round": int(payload.get("round", 0)),
                        "content": payload.get("content", ""),
                    }
                    yield (
                        f"id: {entry['id']}\n"
                        f"data: {json.dumps(data)}\n\n"
                    ).encode("utf-8")
                    cursor = f"({entry['id']}"
                    if data["event"] == "verdict":
                        sent_verdict = True

                if sent_verdict:
                    yield b"event: done\ndata: {}\n\n"
                    break
                await asyncio.sleep(0.2)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable proxy buffering
                "Connection": "keep-alive",
            },
        )

    # ---------- GET /debate/{id}/result ----------

    @app.get("/debate/{session_id}/result")
    async def get_result(session_id: uuid.UUID) -> JSONResponse:
        try:
            row = await db.get_debate(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("get_result: db error: {}", exc)
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        if row is None:
            raise HTTPException(status_code=404, detail="debate not found")
        return DateTimeJSONResponse(content=row)

    # ---------- GET /debates ----------

    @app.get("/debates")
    async def list_debates(
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=20, ge=1, le=100),
    ) -> JSONResponse:
        try:
            payload = await db.list_debates(page=page, page_size=page_size)
        except Exception as exc:  # noqa: BLE001
            logger.error("list_debates: db error: {}", exc)
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        return DateTimeJSONResponse(content=payload)

    # ---------- DELETE /debate/{id} ----------

    @app.delete("/debate/{session_id}")
    async def delete_debate(session_id: uuid.UUID) -> Response:
        try:
            deleted = await db.delete_debate(session_id)
        except Exception as exc:  # noqa: BLE001
            logger.error("delete_debate: db error: {}", exc)
            raise HTTPException(status_code=503, detail="database unavailable") from exc
        # Clean up the Redis stream regardless of whether the DB row
        # existed — idempotent.
        try:
            await asyncio.to_thread(redis_stream.delete_key, str(session_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("delete_debate: redis cleanup failed: {}", exc)
        if not deleted:
            raise HTTPException(status_code=404, detail="debate not found")
        return Response(status_code=204)

    return app


__all__ = ["create_app"]