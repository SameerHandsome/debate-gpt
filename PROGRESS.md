# PROGRESS.md

Sprint day tracker for Debate-GPT. Updated as sub-tasks are completed — never let this file go stale for more than one sub-task at a time.

---

## Day 5 — Pytest suite

**Goal (from PRD §11):** Unit tests (state, schema, aggregation) + integration tests (mocked LLMs). **Done when:** `pytest` passes with >80% line coverage.

### DONE

_(none yet — Day 5 has not started)_

### IN PROGRESS

_(none yet — Day 5 has not started)_

### NOT STARTED

- [ ] Scaffold `tests/` layout: `tests/unit/`, `tests/integration/`, `tests/evals/` (per PRD §9.1 / CLAUDE.md)
- [ ] Add `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock` to `requirements.txt`
- [ ] Add `pytest` config (`pyproject.toml` `[tool.pytest.ini_options]` or `pytest.ini`)
- [ ] Unit tests: `state.py` (round counting, message reducer, list-concat for `round_scores`)
- [ ] Unit tests: `schemas.py` (`RoundScore` validation, `mode="before"` coercion, bool rejection, winner enum)
- [ ] Unit tests: `verdict.py` (swap-aware `pro_total_for_round` / `con_total_for_round`, `tally()`)
- [ ] Unit tests: `prompts.py` smoke (Pro/Con/Judge templates render, Judge never sees "Pro"/"Con" labels)
- [ ] Unit tests: `redis_stream.py` (Upstash REST wrapper — mock `httpx.Client`)
- [ ] Integration tests: FastAPI app via `httpx.AsyncClient` (per PRD §9.1)
  - [ ] `POST /debate/start` → 201 with valid `session_id`
  - [ ] `GET /debate/{id}/stream` → events in order: `pro_token → con_token → judge_score → verdict`
  - [ ] `DELETE /debate/{id}` → 204, cascade removes rounds
  - [ ] `GET /debates` → paginated list with correct schema
  - [ ] `GET /debate/{id}/result` → persisted transcript
  - [ ] `GET /health` → 200/503 + per-dep status
- [ ] Mock LLM fixtures (reuse `FakeLLM` pattern from `dry_run.py`)
- [ ] Run `pytest --cov=src/debate_gpt --cov-report=term-missing` → >80% line coverage
- [ ] Wire `pytest` into a `make test` / `python -m pytest` invocation in README
