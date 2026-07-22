"""Shared pytest fixtures for the Day 5 test suite.

Day 5 tests run fully offline — no real LLM, Redis, or Postgres calls.
`conftest.py` injects in-memory fakes at the public-API boundary:

  * `redis_stream.{xadd, xrange, xlen, delete_key, ping}` → `_InMemoryRedis`
  * `db.{create_debate, complete_debate, fail_debate, get_debate,
        list_debates, delete_debate, ping}` (async) and
    `db.{create_debate_sync, complete_debate_sync, fail_debate_sync}`
        (sync) → `_InMemoryDB`
  * `agents.build_llms` → `{"pro": FakeLLM(...), "con": FakeLLM(...),
                              "judge": FakeLLM(...)}`
  * `db.close_pool` → no-op
  * `observability.health.{ping_redis, ping_db}` → read the in-memory
    stores so the /health endpoint reports what the fakes see

The autouse `mock_infrastructure` fixture handles monkeypatching and
provides a single `app` (FastAPI instance) that the route tests can
drive via httpx.AsyncClient with the ASGI transport.
"""
from __future__ import annotations

import os
import threading
import uuid
from typing import Any, Iterator

import pytest


# --- path bootstrap: src/ is on sys.path the way the launchers put it ---
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SRC = _REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))


# --- env: set the env vars the real modules read at import time --------
# These dummy values satisfy any "DATABASE_URL is not set" / "PING" path
# that slips past the monkeypatches. They are never actually dialed.
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("UPSTASH_REDIS_REST_URL", "https://fake.upstash.io")
os.environ.setdefault("UPSTASH_REDIS_REST_TOKEN", "fake-token")
os.environ.setdefault("GROQ_API_KEY", "fake-groq")
os.environ.setdefault("OPENROUTER_API_KEY", "fake-openrouter")


# ===========================================================================
# In-memory Redis (Upstash REST stand-in)
# ===========================================================================

class _InMemoryRedis:
    """Thread-safe in-memory implementation of the redis_stream surface.

    Mirrors Upstash semantics: XADD returns monotonically increasing
    ids of the form `<ms>-<seq>`, XRANGE returns entries with id >
    `since_id`, XLEN returns 0 for missing keys, DEL is idempotent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._streams: dict[str, list[dict[str, Any]]] = {}
        self._counter = 0

    def _next_id(self) -> str:
        # Real Upstash ids are <ms>-<seq>. We use a fake ms of 0 with a
        # monotonic counter so tests can do ordered comparisons; the
        # id's "shape" is what the SSE handler cares about.
        with self._lock:
            self._counter += 1
            return f"1700-0-{self._counter}"

    def xadd(self, session_id: str, fields: dict[str, str]) -> str:
        entry_id = self._next_id()
        with self._lock:
            self._streams.setdefault(session_id, []).append(
                {"id": entry_id, "fields": dict(fields)}
            )
        return entry_id

    def xrange(self, session_id: str, since_id: str = "-") -> list[dict[str, Any]]:
        with self._lock:
            stream = list(self._streams.get(session_id, []))
        if since_id in ("-", "", None):
            return stream
        # Exclusive cursor `(1700-0-3` is encoded as `1700-0-3` (the
        # leading paren is stripped by the SSE handler; redis_stream
        # itself only sees the bare id).
        if since_id.startswith("("):
            since_id = since_id[1:]
        return [e for e in stream if e["id"] > since_id]

    def xlen(self, session_id: str) -> int:
        with self._lock:
            return len(self._streams.get(session_id, []))

    def delete_key(self, session_id: str) -> None:
        with self._lock:
            self._streams.pop(session_id, None)

    def ping(self) -> bool:
        return True


# ===========================================================================
# In-memory DB (asyncpg + aiosqlite stand-in)
# ===========================================================================

class _InMemoryDB:
    """Thread-safe in-memory replacement for `db` module helpers.

    `create_debate` accepts an explicit `debate_id` so the API's returned
    session_id matches the row PK — the same invariant the real code
    relies on. `complete_debate` writes one `debate_rounds` row per
    round; `delete_debate` cascades by removing both the debate row
    and its child rounds.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._debates: dict[uuid.UUID, dict[str, Any]] = {}
        self._rounds: dict[uuid.UUID, list[dict[str, Any]]] = {}

    # --- async helpers (used by the API route handlers) ---

    async def create_debate(
        self,
        topic: str,
        position_pro: str,
        position_con: str,
        debate_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        with self._lock:
            row_id = debate_id or uuid.uuid4()
            self._debates[row_id] = {
                "id": row_id,
                "topic": topic,
                "position_pro": position_pro,
                "position_con": position_con,
                "status": "pending",
                "winner": None,
                "created_at": "2026-01-01T00:00:00+00:00",
                "completed_at": None,
            }
            self._rounds.setdefault(row_id, [])
            return row_id

    async def complete_debate(
        self,
        debate_id: uuid.UUID,
        winner: str,
        rounds: list[dict[str, Any]],
    ) -> None:
        with self._lock:
            if debate_id not in self._debates:
                return
            self._debates[debate_id]["status"] = "complete"
            self._debates[debate_id]["winner"] = winner
            self._debates[debate_id]["completed_at"] = "2026-01-01T00:00:01+00:00"
            for r in rounds:
                self._rounds[debate_id].append(
                    {
                        "id": uuid.uuid4(),
                        "round_number": int(r["round_number"]),
                        "pro_argument": r["pro"],
                        "con_argument": r["con"],
                        "judge_scores": r["score"],
                        "round_winner": r["winner"],
                        "created_at": "2026-01-01T00:00:01+00:00",
                    }
                )

    async def fail_debate(self, debate_id: uuid.UUID) -> None:
        with self._lock:
            if debate_id not in self._debates:
                return
            self._debates[debate_id]["status"] = "error"
            self._debates[debate_id]["completed_at"] = "2026-01-01T00:00:01+00:00"

    async def get_debate(self, debate_id: uuid.UUID) -> dict[str, Any] | None:
        with self._lock:
            debate = self._debates.get(debate_id)
            if debate is None:
                return None
            return {
                "debate": dict(debate),
                "rounds": [dict(r) for r in self._rounds.get(debate_id, [])],
            }

    async def list_debates(self, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        with self._lock:
            items = list(self._debates.values())
        # Stable order: insertion order.
        total = len(items)
        start = (page - 1) * page_size
        end = start + page_size
        return {
            "page": page,
            "page_size": page_size,
            "total": total,
            "items": [dict(i) for i in items[start:end]],
        }

    async def delete_debate(self, debate_id: uuid.UUID) -> bool:
        with self._lock:
            if debate_id in self._debates:
                del self._debates[debate_id]
                self._rounds.pop(debate_id, None)
                return True
            return False

    async def ping(self) -> bool:
        return True

    # --- sync helpers (used by the BackgroundTasks thread) ---
    # These mirror the async ones; the runtime calls *_sync and we want
    # both the pool-bound and the standalone-connection code paths to be
    # exercised as little as possible — the goal is to confirm the
    # debate runs to completion without asyncpg cross-loop errors, so
    # the sync helpers simply write to the same store.

    def create_debate_sync(
        self,
        topic: str,
        position_pro: str,
        position_con: str,
        debate_id: uuid.UUID | None = None,
    ) -> uuid.UUID:
        import asyncio
        return asyncio.run(
            self.create_debate(topic, position_pro, position_con, debate_id)
        )

    def complete_debate_sync(
        self,
        debate_id: uuid.UUID,
        winner: str,
        rounds: list[dict[str, Any]],
    ) -> None:
        import asyncio
        asyncio.run(self.complete_debate(debate_id, winner, rounds))

    def fail_debate_sync(self, debate_id: uuid.UUID) -> None:
        import asyncio
        asyncio.run(self.fail_debate(debate_id))


# ===========================================================================
# FakeLLM (matches the pattern in dry_run.py; the test version supports
# streaming and per-test scorecard overrides)
# ===========================================================================

class FakeLLM:
    """Synchronous LLM stub that supports `invoke` and `stream`.

    The judge persona returns a JSON scorecard. Tests can override the
    judge content via the constructor or by mutating `judge_content`.

    Streaming yields one chunk containing the full content — enough to
    exercise the runtime's `_stream_and_collect` flush path without
    requiring real tokenization.
    """

    n_pro_calls = 0
    n_con_calls = 0
    n_judge_calls = 0

    def __init__(self, role: str, content: str | None = None) -> None:
        self.role = role
        self._content_override = content
        self.streamed_chunks: list[str] = []

    @property
    def content(self) -> str:
        if self._content_override is not None:
            return self._content_override
        if self.role == "pro":
            FakeLLM.n_pro_calls += 1
            return f"[fake pro round] " + ("X" * 50)
        if self.role == "con":
            FakeLLM.n_con_calls += 1
            return f"[fake con round] " + ("Y" * 50)
        # judge
        FakeLLM.n_judge_calls += 1
        return (
            '{"speaker_a_logic":7,"speaker_a_evidence":6,'
            '"speaker_a_persuasion":5,"speaker_b_logic":7,'
            '"speaker_b_evidence":6,"speaker_b_persuasion":5,'
            '"round_winner":"tie","reasoning":"balanced"}'
        )

    def invoke(self, messages):
        from langchain_core.messages import AIMessage
        return AIMessage(content=self.content, name=self.role.capitalize())

    def stream(self, messages):
        # Yield in one chunk — exercises the runtime's stream loop
        # without needing token-by-token logic in tests.
        self.streamed_chunks.append(self.content)
        yield self.content


def build_fake_llms() -> dict[str, FakeLLM]:
    return {
        "pro": FakeLLM("pro"),
        "con": FakeLLM("con"),
        "judge": FakeLLM("judge"),
    }


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def redis_store() -> _InMemoryRedis:
    return _InMemoryRedis()


@pytest.fixture
def db_store() -> _InMemoryDB:
    return _InMemoryDB()


@pytest.fixture
def mock_infrastructure(
    monkeypatch: pytest.MonkeyPatch,
    redis_store: _InMemoryRedis,
    db_store: _InMemoryDB,
) -> tuple[_InMemoryRedis, _InMemoryDB]:
    """Patch all external I/O boundaries. Returns (redis_store, db_store)."""

    # --- Redis: replace every public function in debate_gpt.redis_stream
    monkeypatch.setattr("debate_gpt.redis_stream.xadd", redis_store.xadd)
    monkeypatch.setattr("debate_gpt.redis_stream.xrange", redis_store.xrange)
    monkeypatch.setattr("debate_gpt.redis_stream.xlen", redis_store.xlen)
    monkeypatch.setattr("debate_gpt.redis_stream.delete_key", redis_store.delete_key)
    monkeypatch.setattr("debate_gpt.redis_stream.ping", redis_store.ping)

    # --- DB async helpers
    monkeypatch.setattr("debate_gpt.db.create_debate", db_store.create_debate)
    monkeypatch.setattr("debate_gpt.db.complete_debate", db_store.complete_debate)
    monkeypatch.setattr("debate_gpt.db.fail_debate", db_store.fail_debate)
    monkeypatch.setattr("debate_gpt.db.get_debate", db_store.get_debate)
    monkeypatch.setattr("debate_gpt.db.list_debates", db_store.list_debates)
    monkeypatch.setattr("debate_gpt.db.delete_debate", db_store.delete_debate)
    monkeypatch.setattr("debate_gpt.db.ping", db_store.ping)
    monkeypatch.setattr("debate_gpt.db.close_pool", lambda: None)

    # --- DB sync helpers (used by the BackgroundTasks runtime thread)
    monkeypatch.setattr(
        "debate_gpt.db.create_debate_sync", db_store.create_debate_sync
    )
    monkeypatch.setattr(
        "debate_gpt.db.complete_debate_sync", db_store.complete_debate_sync
    )
    monkeypatch.setattr("debate_gpt.db.fail_debate_sync", db_store.fail_debate_sync)

    # --- /health: the route calls redis_stream.ping and db.ping, both
    #     of which we already monkeypatched above. No further patching
    #     needed for the happy path; a dedicated `health_down` test
    #     mutates redis_store directly to force a failure.

    # --- LLMs: replace build_llms with the fake triple
    monkeypatch.setattr("debate_gpt.agents.build_llms", build_fake_llms)

    return redis_store, db_store


@pytest.fixture
def app(mock_infrastructure):
    """FastAPI app with all infrastructure mocked."""
    from debate_gpt.api import create_app

    return create_app()


@pytest.fixture
def fake_llm() -> FakeLLM:
    return FakeLLM("pro")


# Make the basic FakeLLM factory easily importable for unit tests
@pytest.fixture
def make_fake_llm():
    def _make(role: str, content: str | None = None) -> FakeLLM:
        return FakeLLM(role, content)
    return _make
