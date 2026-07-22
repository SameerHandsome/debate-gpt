"""Unit tests for `debate_gpt.redis_stream` — Upstash REST wrapper.

The wrapper sends commands as JSON arrays to a single REST endpoint
and parses the `{result: ...} | {error: ...}` shape Upstash returns.
We mock `httpx.Client.post` to feed canned responses into the
`_command` helper, then assert that each public function:

  * formats its arguments into the correct Redis command array
  * parses the response into the right Python type
  * surfaces the right error on failure
  * never lets an unhandled exception leak from `ping` (it returns False)
"""
from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

import debate_gpt.redis_stream as redis_stream


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=MagicMock(), response=MagicMock()
            )


@pytest.fixture
def mock_httpx_post(monkeypatch: pytest.MonkeyPatch):
    """Patch `httpx.Client.post` and capture the last command sent.

    The factory takes a callable `response_factory(*args, **kwargs) -> _FakeResponse`
    and returns (captured, post). To simulate a real Upstash call, set
    `response_factory` to a function that returns the right body.
    """
    captured: dict[str, Any] = {}

    def _install(response_factory):
        def _post(self, url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return response_factory()

        monkeypatch.setattr(httpx.Client, "post", _post)
        # Reset the cached client so the new mock takes effect.
        monkeypatch.setattr(redis_stream, "_client", None)
        return captured

    return _install


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):
    """Required env vars; redis_stream raises if these are missing."""
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://fake.upstash.io")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "fake-token")
    return monkeypatch


# ---------------------------------------------------------------------------
# Required-env behavior
# ---------------------------------------------------------------------------

def test_missing_url_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "x")
    with pytest.raises(RuntimeError, match="UPSTASH_REDIS_REST_URL is not set"):
        redis_stream.xadd("s", {"event": "pro_token", "round": "1", "content": "x"})


def test_missing_token_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://fake.upstash.io")
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="UPSTASH_REDIS_REST_TOKEN is not set"):
        redis_stream.xadd("s", {"event": "pro_token", "round": "1", "content": "x"})


# ---------------------------------------------------------------------------
# xadd
# ---------------------------------------------------------------------------

def test_xadd_sends_xadd_command_with_star_id_and_fields(mock_httpx_post, env):
    captured = mock_httpx_post(lambda: _FakeResponse({"result": "1700-0-1"}))

    out = redis_stream.xadd(
        "sess-1", {"event": "pro_token", "round": "1", "content": "hello"},
    )

    assert out == "1700-0-1"
    # Command array: ["XADD", "debate:stream:sess-1", "*", "event", "pro_token", ...]
    cmd = captured["json"]
    assert cmd[0] == "XADD"
    assert cmd[1] == "debate:stream:sess-1"
    assert cmd[2] == "*"
    # Field/value pairs are flattened in insertion order
    assert cmd[3:] == ["event", "pro_token", "round", "1", "content", "hello"]


def test_xadd_sends_bearer_token_in_auth_header(mock_httpx_post, env):
    captured = mock_httpx_post(lambda: _FakeResponse({"result": "1700-0-1"}))
    redis_stream.xadd("s", {"event": "x", "round": "1", "content": "y"})
    assert captured["headers"]["Authorization"] == "Bearer fake-token"


def test_xadd_stringifies_field_values(mock_httpx_post, env):
    """xadd's signature is dict[str, str] but defensive code should
    not crash on ints; the wire format is always strings."""
    captured = mock_httpx_post(lambda: _FakeResponse({"result": "1700-0-1"}))
    redis_stream.xadd("s", {"event": "verdict", "round": 0, "content": json.dumps({"winner": "pro"})})
    cmd = captured["json"]
    # round=0 should be coerced to "0" on the wire.
    idx = cmd.index("round")
    assert cmd[idx + 1] == "0"


def test_xadd_uses_session_id_in_key(mock_httpx_post, env):
    captured = mock_httpx_post(lambda: _FakeResponse({"result": "x"}))
    redis_stream.xadd("ABC-123", {"event": "x", "round": "1", "content": "y"})
    assert captured["json"][1] == "debate:stream:ABC-123"


# ---------------------------------------------------------------------------
# xrange
# ---------------------------------------------------------------------------

def test_xrange_sends_xrange_command_with_dash_default(mock_httpx_post, env):
    captured = mock_httpx_post(lambda: _FakeResponse({"result": []}))
    redis_stream.xrange("sess")
    cmd = captured["json"]
    assert cmd[0] == "XRANGE"
    assert cmd[1] == "debate:stream:sess"
    assert cmd[2] == "-"
    assert cmd[3] == "+"


def test_xrange_parses_flat_field_pairs_into_dicts(mock_httpx_post, env):
    """Upstash returns fields as [k1, v1, k2, v2, ...] — we must
    pair them up into a dict."""
    raw = [
        ["1700-0-1", ["event", "pro_token", "round", "1", "content", "hi"]],
        ["1700-0-2", ["event", "con_token", "round", "1", "content", "bye"]],
    ]
    mock_httpx_post(lambda: _FakeResponse({"result": raw}))
    out = redis_stream.xrange("sess")
    assert out == [
        {"id": "1700-0-1", "fields": {"event": "pro_token", "round": "1", "content": "hi"}},
        {"id": "1700-0-2", "fields": {"event": "con_token", "round": "1", "content": "bye"}},
    ]


def test_xrange_handles_missing_stream_with_empty_list(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({"result": None}))
    assert redis_stream.xrange("nope") == []


# ---------------------------------------------------------------------------
# xlen
# ---------------------------------------------------------------------------

def test_xlen_returns_int_from_result(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({"result": 5}))
    assert redis_stream.xlen("sess") == 5


def test_xlen_returns_zero_for_missing_key(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({"result": None}))
    assert redis_stream.xlen("nope") == 0


# ---------------------------------------------------------------------------
# delete_key
# ---------------------------------------------------------------------------

def test_delete_key_sends_del_with_prefixed_key(mock_httpx_post, env):
    captured = mock_httpx_post(lambda: _FakeResponse({"result": 1}))
    redis_stream.delete_key("sess-1")
    assert captured["json"] == ["DEL", "debate:stream:sess-1"]


def test_delete_key_is_idempotent_on_missing_key(mock_httpx_post, env):
    """No exception is raised when the key doesn't exist (Upstash
    returns 0, which we silently ignore)."""
    mock_httpx_post(lambda: _FakeResponse({"result": 0}))
    redis_stream.delete_key("nope")  # must not raise


# ---------------------------------------------------------------------------
# ping
# ---------------------------------------------------------------------------

def test_ping_returns_true_on_pong(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({"result": "PONG"}))
    assert redis_stream.ping() is True


def test_ping_returns_false_on_non_pong_response(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({"result": "NOPE"}))
    assert redis_stream.ping() is False


def test_ping_returns_false_on_exception(mock_httpx_post, env):
    """ping() is called from /health; it must never raise."""

    def _explode():
        raise RuntimeError("upstash down")

    mock_httpx_post(_explode)
    assert redis_stream.ping() is False


def test_ping_returns_false_on_http_status_error(mock_httpx_post, env):
    mock_httpx_post(lambda: _FakeResponse({}, status_code=500))
    assert redis_stream.ping() is False


# ---------------------------------------------------------------------------
# HTTP-layer error handling
# ---------------------------------------------------------------------------

def test_command_raises_on_5xx(mock_httpx_post, env):
    """`xadd` / `xrange` / `xlen` / `delete_key` are not protected
    by a `try/except` like `ping`. The route handlers wrap them
    in their own try/except, so we just confirm the raw behavior."""
    mock_httpx_post(lambda: _FakeResponse({}, status_code=503))
    with pytest.raises(httpx.HTTPStatusError):
        redis_stream.xadd("s", {"event": "x", "round": "1", "content": "y"})


# ---------------------------------------------------------------------------
# Key shape — exposed by the module constant
# ---------------------------------------------------------------------------

def test_stream_key_prefix_constant():
    """`_STREAM_PREFIX` is the contract the SSE handler and runtime
    depend on. A regression here breaks everything downstream."""
    assert redis_stream._STREAM_PREFIX == "debate:stream:"
