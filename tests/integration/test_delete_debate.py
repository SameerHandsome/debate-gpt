"""Integration tests: DELETE /debate/{id} cascade behavior.

The `ON DELETE CASCADE` from migration 0001 removes `debate_rounds`
rows atomically when a `debates` row is deleted (PRD §6). The
mid-turn PRD spec calls this out: tests must verify the cascade
removes the children, not just the 204 status.

We also test:
  * DELETE returns 404 for an unknown session_id.
  * DELETE cleans up the Redis stream (the route calls
    `redis_stream.delete_key` in a try/except).
  * DELETE is idempotent (a second DELETE on the same id 404s).
  * DELETE does not 5xx when the Redis cleanup fails (the cleanup
    is best-effort).
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from httpx import ASGITransport

from tests.integration.test_debate_api import _wait_for_debate_complete

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Cascade behavior
# ---------------------------------------------------------------------------

async def test_delete_debate_returns_204_and_cascades_rounds(app, db_store):
    """Create a complete debate, then DELETE it. Assert:
      * HTTP 204
      * The debate row is gone
      * The cascade actually removed the debate_rounds rows
        (verified by directly querying the in-memory store, not
        by relying on the response alone)."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start",
            json={"topic": "Delete me", "max_rounds": 3},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        # Sanity: rounds exist before delete
        before = await db_store.get_debate(uuid.UUID(sid))
        assert before is not None
        assert len(before["rounds"]) == 3

        r = await client.delete(f"/debate/{sid}")

    assert r.status_code == 204
    assert r.content == b""

    # Cascade verification — follow-up DB check.
    after = await db_store.get_debate(uuid.UUID(sid))
    assert after is None
    # The in-memory rounds list must also be gone (cascade).
    assert uuid.UUID(sid) not in db_store._rounds


async def test_delete_debate_cascades_with_single_round(app, db_store):
    """Smoke test the cascade with a 2-round debate."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Tiny", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        r = await client.delete(f"/debate/{sid}")

    assert r.status_code == 204
    after = await db_store.get_debate(uuid.UUID(sid))
    assert after is None


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

async def test_delete_unknown_session_returns_404(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/debate/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_delete_malformed_uuid_returns_422(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete("/debate/not-a-uuid")
    assert r.status_code == 422


async def test_delete_is_not_idempotent_returns_404_on_second_call(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Idempotency", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        r1 = await client.delete(f"/debate/{sid}")
        r2 = await client.delete(f"/debate/{sid}")

    assert r1.status_code == 204
    assert r2.status_code == 404


# ---------------------------------------------------------------------------
# Redis cleanup
# ---------------------------------------------------------------------------

async def test_delete_also_removes_redis_stream(app, db_store, redis_store):
    """The route's Redis cleanup is best-effort but must run on
    the happy path. We populate the stream directly and confirm
    it's gone after DELETE."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Redis cleanup", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        # The runtime has XADDed events; confirm the stream has entries.
        assert redis_store.xlen(sid) > 0

        r = await client.delete(f"/debate/{sid}")

    assert r.status_code == 204
    # Stream must be gone.
    assert redis_store.xlen(sid) == 0


async def test_delete_succeeds_even_when_redis_cleanup_fails(app, db_store, monkeypatch):
    """If redis_stream.delete_key raises, the route catches and
    still returns 204 (the DB delete is the source of truth)."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Redis fail", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

    # Now monkeypatch the patched redis_stream.delete_key to raise.
    def _explode(_session_id):
        raise RuntimeError("redis down")

    monkeypatch.setattr("debate_gpt.redis_stream.delete_key", _explode)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.delete(f"/debate/{sid}")
    # 204 because the DB delete succeeded; the Redis cleanup is best-effort.
    assert r.status_code == 204
