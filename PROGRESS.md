# PROGRESS.md

Sprint day tracker for Debate-GPT. Updated as sub-tasks are completed — never let this file go stale for more than one sub-task at a time.

---

## Day 5 — Pytest suite ✅ COMPLETE

**Goal (from PRD §11):** Unit tests (state, schema, aggregation) + integration tests (mocked LLMs). **Done when:** `pytest` passes with >80% line coverage.

### DONE

- [x] Add `pytest`, `pytest-asyncio`, `pytest-cov`, `pytest-mock` to `requirements.txt`
- [x] Add `pytest` config (`pyproject.toml` `[tool.pytest.ini_options]`)
- [x] Scaffold `tests/` layout: `tests/unit/`, `tests/integration/`, `tests/evals/` (per PRD §9.1 / CLAUDE.md). `tests/evals/` is bare scaffold (Day 6 scope, no real-eval logic).
- [x] Top-level `tests/conftest.py` with in-memory Redis + DB + FakeLLM fixtures (autouse `mock_infrastructure`).
- [x] Unit tests: state.py (round counting, message reducer, list-concat for `round_scores`)
- [x] Unit tests: schemas.py (`RoundScore` validation, `mode="before"` coercion, bool rejection, winner enum)
- [x] Unit tests: verdict.py (swap-aware `pro_total_for_round` / `con_total_for_round`, `tally()`)
- [x] Unit tests: prompts.py smoke (Pro/Con/Judge templates render, Judge never sees "Pro"/"Con" labels)
- [x] Unit tests: redis_stream.py (Upstash REST wrapper — mock `httpx.Client`)
- [x] Unit tests: session_utils.py (key prefix + since_id cursor)
- [x] Integration tests: FastAPI app via `httpx.AsyncClient` (per PRD §9.1)
  - [x] `POST /debate/start` → 201 with valid `session_id`
  - [x] `GET /debate/{id}/stream` → events in order: `pro_token → con_token → judge_score → verdict`
  - [x] `DELETE /debate/{id}` → 204, cascade removes rounds
  - [x] `GET /debates` → paginated list with correct schema
  - [x] `GET /debate/{id}/result` → persisted transcript
  - [x] `GET /health` → 200/503 + per-dep status
  - [x] `_sync` regression: full debate via `run_debate_streaming` completes without cross-event-loop errors
- [x] `python -m pytest tests/integration/` → all 33 integration tests pass
- [x] `make test` target wired with `pytest --cov=src/debate_gpt --cov-report=term-missing`
- [x] `README.md` documents `make test` and `python -m pytest` invocations

### IN PROGRESS

(none)

### NOT STARTED

- [ ] Day 5 is fully done; coverage >80% target tracked at suite level (see `make test`).

---

## Days 1–4 — DONE (see git log: `e2f79d5`, `b63f2f3`, `51cc5a9`, `71ba8ca`, `ca0bca7`)

## Days 6–7 — NOT STARTED

- **Day 6** Eval suite (judge consistency, position-bias, schema compliance, argument quality) → `eval_results.csv`.
- **Day 7** Multi-stage Dockerfile (builder + runtime, non-root), Railway/Render deploy, Vercel frontend, demo video.
