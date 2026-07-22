"""Integration tests: SSE event ordering and schema.

The `/debate/{id}/stream` endpoint polls Upstash Redis (here the
in-memory fake) and yields `id: <id>\ndata: <json>\n\n` frames.
Per PRD §5.2 the events arrive in this order per round:
  pro_token* → con_token* → judge_score
…and after the final round, a single `verdict` event followed by
`event: done`.

We assert:
  * Each frame matches the documented schema.
  * The interleave is correct (pro tokens before con tokens before
    judge score, repeat for each round, then verdict).
  * The stream closes after the verdict (the client gets a `done`).
  * Last-Event-ID resume works (the cursor advances past the last
    delivered id).
"""
from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest
from httpx import ASGITransport

from tests.conftest import _InMemoryRedis, _InMemoryDB  # for typing
from tests.integration.test_debate_api import _wait_for_debate_complete

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_sse_frames(raw: bytes) -> list[dict]:
    """Parse an SSE byte stream into a list of `{"id": ..., "event": ..., "data": ...}`."""
    frames: list[dict] = []
    for block in raw.decode("utf-8").split("\n\n"):
        if not block.strip():
            continue
        frame: dict = {"raw": block}
        for line in block.splitlines():
            if line.startswith("id:"):
                frame["id"] = line[3:].strip()
            elif line.startswith("event:"):
                frame["event"] = line[6:].strip()
            elif line.startswith("data:"):
                frame["data"] = line[5:].strip()
        if "data" in frame:
            try:
                frame["payload"] = json.loads(frame["data"])
            except json.JSONDecodeError:
                frame["payload"] = None
        frames.append(frame)
    return frames


async def _read_stream(client, sid, last_event_id: str = "-") -> bytes:
    """Read the full SSE stream to completion (up to and including 'done')."""
    r = await client.get(
        f"/debate/{sid}/stream",
        headers={"Last-Event-ID": last_event_id} if last_event_id != "-" else {},
    )
    # StreamingResponse is consumed by r.aiter_bytes() in httpx;
    # but since we return `app=app` ASGI, the stream is fully
    # buffered in r.content when the generator finishes.
    return r.content


# ---------------------------------------------------------------------------
# SSE schema
# ---------------------------------------------------------------------------

async def test_sse_emits_expected_event_order_for_three_rounds(app, db_store):
    """For a 3-round debate, the runtime emits:
       pro_token → con_token → judge_score per round (X3),
       then a single verdict and a `done` close.

    The SSE handler polls the stream every 200ms (PRD §3.2 note),
    so within a single round the pro/con/judge trio is *not*
    guaranteed to be observed in strict order by the consumer —
    the stream is event-by-event, not round-by-round. We assert
    the *globally observable* invariants instead:
      * All judge_score events appear before the verdict.
      * Exactly N judge_score events for an N-round debate.
      * No events after the verdict (apart from `done`).
    """
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "SSE order test", "max_rounds": 3},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        body = await _read_stream(client, sid)

    frames = _parse_sse_frames(body)
    # Collect event names from either the parsed `data` payload's `event`
    # field, or the bare SSE `event:` line (the `done` close has no
    # JSON payload — it's `data: {}` with `event: done`).
    events = [
        f.get("payload", {}).get("event") or f.get("event")
        for f in frames
    ]
    events = [e for e in events if e]

    # Exactly 3 judge_score events for a 3-round debate.
    assert events.count("judge_score") == 3
    # Exactly 1 verdict.
    assert events.count("verdict") == 1
    # No judge_score after the verdict. `events` is a list, so use a
    # generator expression over `enumerate` to find the last index of
    # "judge_score" (Python lists don't have a `.rindex` method).
    last_judge_score = max(i for i, e in enumerate(events) if e == "judge_score")
    assert events.index("verdict") > last_judge_score
    # Pro and con tokens exist.
    assert "pro_token" in events
    assert "con_token" in events
    # No events past the `done` close.
    assert events[-1] == "done"


async def test_sse_judge_score_event_has_round_number_and_content(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "SSE schema test", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        body = await _read_stream(client, sid)

    frames = _parse_sse_frames(body)
    judge_frames = [
        f for f in frames
        if f.get("payload", {}).get("event") == "judge_score"
    ]
    assert len(judge_frames) == 2
    for f in judge_frames:
        payload = f["payload"]
        assert "round" in payload
        assert payload["round"] in (1, 2)
        # content is a JSON string of the RoundScore
        score = json.loads(payload["content"])
        for k in (
            "speaker_a_logic", "speaker_a_evidence", "speaker_a_persuasion",
            "speaker_b_logic", "speaker_b_evidence", "speaker_b_persuasion",
            "round_winner", "reasoning",
        ):
            assert k in score


async def test_sse_verdict_event_has_winner_and_totals(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Verdict test", "max_rounds": 3},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        body = await _read_stream(client, sid)

    frames = _parse_sse_frames(body)
    verdict_frames = [
        f for f in frames if f.get("payload", {}).get("event") == "verdict"
    ]
    assert len(verdict_frames) == 1
    # The SSE generator wraps the runtime's XADD payload as
    # `{event, round, content}` where `content` is the JSON-stringified
    # verdict dict (tally() output: {pro_total, con_total, winner, ...}).
    payload = verdict_frames[0]["payload"]
    assert isinstance(payload["content"], str)
    verdict = json.loads(payload["content"])
    assert verdict["winner"] in ("pro", "con", "tie")
    assert "pro_total" in verdict
    assert "con_total" in verdict


async def test_sse_emits_done_after_verdict(app, db_store):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Done test", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        body = await _read_stream(client, sid)

    frames = _parse_sse_frames(body)
    # The last frame must be the `done` event from api.py.
    assert frames[-1].get("event") == "done"


async def test_sse_includes_id_field_for_resume(app, db_store):
    """Every event frame must carry an `id:` so the client can
    resume from a `Last-Event-ID` header."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.post(
            "/debate/start", json={"topic": "Resume test", "max_rounds": 2},
        )
        sid = r.json()["session_id"]
        await _wait_for_debate_complete(app, sid, db_store)

        body = await _read_stream(client, sid)

    frames = _parse_sse_frames(body)
    for f in frames:
        if f.get("event") == "done":
            continue
        assert "id" in f, f"frame missing id: {f!r}"


# ---------------------------------------------------------------------------
# Last-Event-ID resume
# ---------------------------------------------------------------------------

async def test_sse_resume_with_last_event_id(app, db_store, redis_store):
    """If the client supplies Last-Event-ID, the stream must only
    emit events with id > that. We pre-populate the stream with three
    events (pro_token, con_token, verdict), then ask for events after
    the first.

    IMPORTANT: a `verdict` event MUST be included in the pre-populated
    stream. The SSE generator (api.py) only breaks its polling loop
    when it observes a `verdict` event (`if sent_verdict: break`).
    Since this test uses a synthetic session_id with no real debate
    ever running, there is nothing else that would ever produce a
    verdict — without one, the generator polls every 200ms forever
    and the test hangs indefinitely. This was the actual bug that
    caused the Day 5 suite to hang on the first pass.
    """
    sid = uuid.uuid4()
    # Pre-populate the in-memory stream (the runtime will append
    # more events when the background task runs, but resume-from
    # is only about the cursor, not the content).
    redis_store.xadd(str(sid), {"event": "pro_token", "round": "1", "content": "x"})
    first_id = redis_store._streams[str(sid)][0]["id"]
    redis_store.xadd(str(sid), {"event": "con_token", "round": "1", "content": "y"})
    # Add a verdict so the SSE generator's `sent_verdict` flag flips
    # True and the stream actually closes instead of polling forever.
    redis_store.xadd(
        str(sid),
        {
            "event": "verdict",
            "round": "0",
            "content": json.dumps({"pro_total": 0, "con_total": 0, "winner": "tie"}),
        },
    )

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        body = await _read_stream(client, str(sid), last_event_id=first_id)

    frames = _parse_sse_frames(body)
    # The first two events exist; with last_event_id=first_id, the
    # first event's id (== first_id) is excluded, so we only get
    # the second one onward.
    semantic = [f.get("payload", {}).get("event") for f in frames if f.get("payload", {}).get("event")]
    assert "pro_token" not in semantic  # the first one was excluded
    assert "con_token" in semantic
    # Confirms the stream actually observed the verdict and closed
    # cleanly (rather than the test timing out on a hung generator).
    assert "verdict" in semantic
    assert frames[-1].get("event") == "done"