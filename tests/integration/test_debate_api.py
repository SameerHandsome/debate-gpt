"""Integration tests: full POST /debate/start → SSE → GET /result flow.

These tests drive the FastAPI app via httpx.AsyncClient with the
ASGI transport. The autouse `mock_infrastructure` fixture in
`tests/conftest.py` replaces every external I/O boundary with an
in-memory fake, so the tests run fully offline and are fast.

The most important test in this file is `test_full_debate_flow_via
_background_task` — it exercises `run_debate_streaming` end-to-end
inside FastAPI's BackgroundTasks thread. This is the path that
historically hit the cross-event-loop asyncpg errors on Day 3
(see CLAUDE.md: "sync helpers spin up `asyncio.run` with a standalone
connection, not the shared pool"). We confirm the in-memory store
receives the same rows it would have, and that no exception leaks
to the test process.
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from httpx import ASGITransport

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _wait_for_debate_complete(
    app,
    session_id: str,
    db_store,
    timeout: float = 5.0,
    poll_interval: float = 0.05,
) -> dict:
    """Poll the in-memory DB until the debate is complete or timeout.

    The runtime runs in FastAPI's BackgroundTasks thread, so we wait
    by re-querying the in-memory store directly (the test owns it).
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        result = await db_store.get_debate(uuid.UUID(session_id))
        if result and result["debate"]["status"] in ("complete", "error"):
            return result
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"debate {session_id} did not complete within {timeout}s; "
                f"last status: {result['debate']['status'] if result else None}"
            )
        await asyncio.sleep(poll_interval)


# ---------------------------------------------------------------------------
# POST /debate/start
# ---------------------------------------------------------------------------

async def test_post_start_debate_returns_201_with_valid_session_id(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/debate/start", json={"topic": "Should AI be regulated?"})

    assert r.status_code == 201
    body = r.json()
    assert "session_id" in body
    assert body["status"] == "pending"
    # session_id must be a valid UUID4 string
    sid = uuid.UUID(body["session_id"])
    assert sid.version == 4


async def test_post_start_debate_creates_pending_row_in_db(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Test topic", "max_rounds": 2},
        )
    body = r.json()
    sid = uuid.UUID(body["session_id"])

    result = await db_store.get_debate(sid)
    assert result is not None
    assert result["debate"]["topic"] == "Test topic"
    assert result["debate"]["status"] in ("pending", "running", "complete")
    assert result["debate"]["position_pro"] == "For: Test topic"
    assert result["debate"]["position_con"] == "Against: Test topic"


async def test_post_start_debate_clamps_rounds_when_unspecified(app, db_store, monkeypatch):
    """The server falls back to MAX_ROUNDS env var (default 3) when
    the client doesn't specify. We assert the runtime is invoked with
    the default 3 by checking the row's eventual completion matches."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/debate/start", json={"topic": "default rounds test"})

    body = r.json()
    sid = uuid.UUID(body["session_id"])
    result = await _wait_for_debate_complete(app, body["session_id"], db_store)

    # The default is 3 rounds → 3 debate_rounds rows.
    assert len(result["rounds"]) == 3


async def test_post_start_debate_rejects_too_short_topic(app):
    """Topic min_length=3 in the StartDebateRequest schema."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post("/debate/start", json={"topic": "ab"})

    assert r.status_code == 422


async def test_post_start_debate_rejects_out_of_range_rounds(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Test topic", "max_rounds": 6},
        )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Full background-task path: the _sync regression check
# ---------------------------------------------------------------------------

async def test_full_debate_flow_via_background_task(app, db_store):
    """POST /debate/start → background task runs to completion →
    /result returns the persisted transcript with N rounds.

    This is the path that broke on Day 3 with cross-event-loop
    asyncpg errors. The conftest's in-memory *_sync helpers don't
    touch asyncpg, but we still exercise the runtime's `for round in
    range(...)` loop and its `db.complete_debate_sync` call, which
    is what was failing before.
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Should AI be regulated?", "max_rounds": 3},
        )
    assert r.status_code == 201
    body = r.json()
    sid_str = body["session_id"]

    result = await _wait_for_debate_complete(app, sid_str, db_store)

    # Debate row is complete with a non-null winner
    assert result["debate"]["status"] == "complete"
    assert result["debate"]["winner"] in ("pro", "con", "tie")
    assert result["debate"]["completed_at"] is not None

    # 3 round rows persisted, in order
    assert len(result["rounds"]) == 3
    for i, r in enumerate(result["rounds"], start=1):
        assert r["round_number"] == i
        assert r["pro_argument"]
        assert r["con_argument"]
        assert r["judge_scores"]
        assert r["round_winner"] in ("pro", "con", "tie")


async def test_background_task_persists_scorecard_fields(app, db_store):
    """Each round's judge_scores JSONB must contain the full
    RoundScore fields plus the runtime-added pro_score / con_score."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Test", "max_rounds": 2},
        )
    body = r.json()
    result = await _wait_for_debate_complete(app, body["session_id"], db_store)

    for r in result["rounds"]:
        scores = r["judge_scores"]
        for k in (
            "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
            "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
            "round_winner", "reasoning",
            "pro_score", "con_score",  # runtime-added
        ):
            assert k in scores, f"missing {k} in {scores!r}"


async def test_background_task_with_two_rounds(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Test", "max_rounds": 2},
        )
    body = r.json()
    result = await _wait_for_debate_complete(app, body["session_id"], db_store)
    assert len(result["rounds"]) == 2


# ---------------------------------------------------------------------------
# GET /debate/{id}/result
# ---------------------------------------------------------------------------

async def test_get_result_returns_full_transcript(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Result test", "max_rounds": 3},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        r = await client.get(f"/debate/{sid}/result")

    assert r.status_code == 200
    payload = r.json()
    assert payload["debate"]["topic"] == "Result test"
    assert payload["debate"]["winner"] in ("pro", "con", "tie")
    assert len(payload["rounds"]) == 3


async def test_get_result_404_for_unknown_session(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get(f"/debate/{uuid.uuid4()}/result")
    assert r.status_code == 404


async def test_get_result_400_for_malformed_session_id(app):
    """The route declares `session_id: uuid.UUID` — non-UUID input
    should be rejected by FastAPI before reaching the handler."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/debate/not-a-uuid/result")
    assert r.status_code == 422  # FastAPI's UUID validation


# ---------------------------------------------------------------------------
# GET /debates (paginated list)
# ---------------------------------------------------------------------------

async def test_list_debates_returns_paginated_list_with_correct_schema(app, db_store):
    """Insert 3 debates directly into the in-memory store, then list."""
    for i in range(3):
        await db_store.create_debate(
            topic=f"Topic {i}",
            position_pro=f"For: Topic {i}",
            position_con=f"Against: Topic {i}",
        )

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/debates?page=1&page_size=10")

    assert r.status_code == 200
    payload = r.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 10
    assert payload["total"] == 3
    assert len(payload["items"]) == 3
    for item in payload["items"]:
        # Summary fields per db.list_debates
        assert "id" in item
        assert "topic" in item
        assert "status" in item
        # No nested rounds in the list view
        assert "rounds" not in item


async def test_list_debates_pagination_clamps_to_page_size(app, db_store):
    for i in range(5):
        await db_store.create_debate(
            topic=f"Topic {i}",
            position_pro=f"For: Topic {i}",
            position_con=f"Against: Topic {i}",
        )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/debates?page=1&page_size=2")

    assert r.status_code == 200
    payload = r.json()
    assert payload["page"] == 1
    assert payload["page_size"] == 2
    assert payload["total"] == 5
    assert len(payload["items"]) == 2


async def test_list_debates_empty_returns_zero_total(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/debates")
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["items"] == []
