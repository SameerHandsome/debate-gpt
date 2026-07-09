"""loguru setup with stdlib-log interception, console + JSON sinks, and
an optional async Loki sink.

The default export `logger` is a loguru `logger` object. Downstream code
can do `from debate_gpt.observability.logging import logger` or use the
top-level re-export.

Per PRD §11.1:
- JSON sink (always on) — `logs/debate-gpt.jsonl`, line-delimited.
- Human-readable console sink (always on) — colored, level + extras.
- Loki sink (gated on `LOKI_ENABLED=true`) — async push via
  `httpx.AsyncClient`, background worker draining an `asyncio.Queue`.
  Falls back to console/JSON if Loki is unreachable.
- Intercept uvicorn / FastAPI / asyncpg stdlib logging via
  `InterceptHandler` (loguru's standard recipe).

Standard fields attached to every record via `logger.contextualize`:
- request_id (UUID4 from middleware, "-" otherwise)
- trace_id ("-" until LangSmith wiring lands)
- session_id ("-" outside a debate)
- node_name ("-" outside a LangGraph node)
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from typing import Any

import httpx
from loguru import logger as _loguru_logger

# Sentinel for "no value"; loguru's default str() would print "None".
_NA = "-"


class InterceptHandler(logging.Handler):
    """Route stdlib `logging` records through loguru.

    Standard recipe from the loguru README.
    """

    def emit(self, record: logging.LogRecord) -> None:  # noqa: D401
        try:
            level = _loguru_logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        _loguru_logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


# ---------- Sinks ----------

def _console_format(record: dict) -> str:
    extra = record["extra"]
    return (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <5}</level> | "
        f"req={extra.get('request_id', _NA):<8} | "
        f"trc={extra.get('trace_id', _NA):<8} | "
        f"ses={extra.get('session_id', _NA):<36} | "
        f"node={extra.get('node_name', _NA):<12} | "
        "{name}:{function}:{line} — {message}\n"
    )


# ---------- Optional async Loki sink ----------

class _LokiSink:
    """Background worker that pushes log records to Grafana Loki.

    `enqueue(record)` from a sync context is a non-blocking `put_nowait`
    into an `asyncio.Queue`. The worker coroutine POSTs batches to
    `LOKI_URL/loki/api/v1/push`. On any error, it logs a single
    WARNING to the console sink and keeps running — no app stall.
    """

    def __init__(self, loki_url: str) -> None:
        self._url = loki_url.rstrip("/") + "/loki/api/v1/push"
        self._queue: asyncio.Queue[dict] | None = None
        self._task: asyncio.Task | None = None
        self._client: httpx.AsyncClient | None = None

    def enqueue(self, record: dict) -> None:
        if self._queue is None:
            return
        try:
            self._queue.put_nowait(record)
        except asyncio.QueueFull:
            # Drop on overflow. The console + JSON sinks still capture it.
            pass

    async def start(self) -> None:
        if self._task is not None:
            return
        self._queue = asyncio.Queue(maxsize=1000)
        self._client = httpx.AsyncClient(timeout=2.0)
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._queue = None

    async def _run(self) -> None:
        assert self._queue is not None and self._client is not None
        while True:
            record = await self._queue.get()
            try:
                payload = self._format(record)
                await self._client.post(self._url, json=payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # Single warning — don't spam.
                _loguru_logger.warning(
                    "loki sink push failed: {}", exc
                )

    def _format(self, record: dict) -> dict:
        """Translate a loguru record into Loki's push payload shape."""
        extra = record.get("extra", {})
        message = record["message"]
        record_time_ns = int(record["time"].timestamp() * 1_000_000_000)
        level = record["level"].name
        # Each line is one stream entry; the unique-by-label contract is
        # {job, level}. (Loki requires labels; we use minimal ones.)
        return {
            "streams": [
                {
                    "labels": '{job="debate-gpt",level="'
                    + level.lower() + '"}',
                    "entries": [
                        {
                            "ts": str(record_time_ns),
                            "line": (
                                f"ts={record['time'].isoformat()} "
                                f"level={level} "
                                f"request_id={extra.get('request_id', _NA)} "
                                f"trace_id={extra.get('trace_id', _NA)} "
                                f"session_id={extra.get('session_id', _NA)} "
                                f"node_name={extra.get('node_name', _NA)} "
                                f"logger={record['name']} "
                                f"msg={message!r}"
                            ),
                        }
                    ],
                }
            ]
        }


_loki_sink: _LokiSink | None = None


def _loki_pusher(record: dict) -> None:
    if _loki_sink is not None:
        _loki_sink.enqueue(record)


# ---------- Configuration ----------

def configure_logging() -> None:
    """One-shot setup. Idempotent — safe to call multiple times."""
    global _loki_sink

    # 1. Reset loguru (so re-import in tests doesn't double-add sinks).
    _loguru_logger.remove()

    # 2. Always-on console sink.
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    _loguru_logger.add(
        sys.stderr,
        level=log_level,
        format=_console_format,
        colorize=True,
        enqueue=False,
    )

    # 3. Always-on JSON sink.
    os.makedirs("logs", exist_ok=True)
    _loguru_logger.add(
        "logs/debate-gpt.jsonl",
        level="INFO",
        serialize=True,
        enqueue=True,  # safe across threads
    )

    # 4. Optional Loki sink (sink is attached at configure_logging time;
    # the worker task starts on first event-loop — see start_loki_worker).
    if os.getenv("LOKI_ENABLED", "false").lower() == "true":
        loki_url = os.getenv("LOKI_URL", "").rstrip("/")
        if loki_url:
            _loki_sink = _LokiSink(loki_url)
            _loguru_logger.add(
                _loki_pusher,
                level="INFO",
                format="{message}",
                # No filter — every record is sent (but the worker
                # backpressures via the bounded queue).
            )
        else:
            _loguru_logger.warning(
                "LOKI_ENABLED=true but LOKI_URL is empty; "
                "skipping Loki sink (console + JSON still active)"
            )

    # 5. Intercept stdlib logging.
    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access",
                  "fastapi", "asyncpg", "httpx"):
        lg = logging.getLogger(noisy)
        lg.handlers = [InterceptHandler()]
        lg.propagate = False

    _loguru_logger.info(
        "logging configured: level={} loki={}",
        log_level,
        "on" if _loki_sink is not None else "off",
    )


async def start_loki_worker() -> None:
    """Start the async Loki worker. Call from FastAPI lifespan startup."""
    if _loki_sink is not None:
        await _loki_sink.start()


async def stop_loki_worker() -> None:
    """Stop the async Loki worker. Call from FastAPI lifespan shutdown."""
    if _loki_sink is not None:
        await _loki_sink.stop()


# Re-export for downstream `from debate_gpt.observability.logging import logger`.
logger = _loguru_logger


__all__ = [
    "configure_logging",
    "logger",
    "start_loki_worker",
    "stop_loki_worker",
]
