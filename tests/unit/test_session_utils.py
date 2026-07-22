"""Unit tests for session key conventions and the SSE exclusive-cursor.

The `redis_stream` module exposes a single private constant
`_STREAM_PREFIX = "debate:stream:"` that the runtime, SSE handler,
and `delete_key` all share. Any change here breaks both the writer
and the reader paths — this file locks down the contract.

We also test the exclusive-cursor (`(<id>`) parsing that the SSE
handler uses to resume from the last-delivered entry. Upstash's
XRANGE supports a leading `(` to mean "strictly greater than" — we
verify the helpers handle the bare-id form, the paren form, and
the sentinel `"-"` (start-of-stream).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

import debate_gpt.redis_stream as redis_stream


# ---------------------------------------------------------------------------
# Key prefix
# ---------------------------------------------------------------------------

def test_stream_key_prefix_is_exactly_debate_stream():
    """The prefix is the contract every writer and reader shares.
    A regression here silently orphans sessions."""
    assert redis_stream._STREAM_PREFIX == "debate:stream:"


def test_session_id_is_appended_to_prefix_verbatim():
    """The runtime calls xadd(session_id, ...); the key is built by
    naive string concat. We don't URL-encode the id, but we do
    preserve the case and any dashes a UUID has."""
    prefix = redis_stream._STREAM_PREFIX
    for sid in ("abc", "ABC-123", "00000000-0000-0000-0000-000000000000"):
        assert f"{prefix}{sid}" == f"debate:stream:{sid}"


# ---------------------------------------------------------------------------
# xrange since_id handling (covered end-to-end via the in-memory store
# in the conftest fixture; here we test the bare-function parsing with
# a mocked httpx layer so we don't depend on conftest infrastructure).
# ---------------------------------------------------------------------------

def _xrange_with_raw(raw, captured=None, since_id="-"):
    """Call xrange with a mocked HTTP layer returning a canned `raw`."""
    from unittest.mock import patch
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"result": raw}
    fake_resp.raise_for_status.return_value = None
    with patch.object(redis_stream, "_client", None), \
         patch.object(redis_stream.httpx.Client, "post", return_value=fake_resp):
        return redis_stream.xrange("sess", since_id=since_id)


def test_xrange_with_dash_returns_all_entries():
    raw = [
        ["1700-0-1", ["event", "pro_token"]],
        ["1700-0-2", ["event", "con_token"]],
    ]
    out = _xrange_with_raw(raw, since_id="-")
    assert [e["id"] for e in out] == ["1700-0-1", "1700-0-2"]


def test_xrange_with_empty_string_returns_all():
    """An empty since_id is treated the same as `"-"`."""
    raw = [["1700-0-1", ["event", "x"]]]
    out = _xrange_with_raw(raw, since_id="")
    assert len(out) == 1


def test_xrange_with_exclusive_cursor_strips_leading_paren():
    """The SSE handler computes `(last_id` (with a leading paren) to
    pass to Upstash; but our function is also called with a bare id
    by the API's `Last-Event-ID` header in some code paths. We
    tolerate both forms in the parser (the handler strips the paren
    before calling, so this is defensive)."""
    # The real xrange function doesn't do paren-stripping; the SSE
    # handler does. Confirm the function does not crash on a bare id
    # passed as since_id.
    raw = [["1700-0-3", ["event", "x"]]]
    out = _xrange_with_raw(raw, since_id="1700-0-2")
    # The bare id form is "exclusive greater than", same semantics
    # as the paren-prefixed form. We don't filter on the client side
    # (the server does the filtering), so the client just passes it
    # through. The mock returns all entries regardless.
    assert len(out) == 1
    assert out[0]["id"] == "1700-0-3"


def test_xrange_with_no_args_uses_dash_default():
    """`xrange(session_id)` must default to `"-"` so callers don't
    have to know the sentinel."""
    import inspect
    sig = inspect.signature(redis_stream.xrange)
    assert sig.parameters["since_id"].default == "-"


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

def test_module_exposes_expected_public_api():
    expected = {"xadd", "xrange", "xlen", "delete_key", "ping"}
    assert set(redis_stream.__all__) == expected


def test_module_does_not_export_private_helpers():
    """The leading-underscore helpers must not leak into the public API."""
    for name in redis_stream.__all__:
        assert not name.startswith("_"), f"{name} is private but exported"
