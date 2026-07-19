# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project: Debate-GPT

Multi-agent AI debate platform. Two LLM agents argue opposing sides of a user-supplied topic, a third (more powerful) model scores each round as an impartial judge, and a final verdict is declared. The full PRD lives in `PRD.md` — read it before changing architecture.

Current state: **Day 4 in progress** (FastAPI + SSE + Neon Postgres + Upstash Redis Streams + observability foundations done; React frontend scaffolding landed under `frontend/`, end-to-end manual smoke test in `tests/manual_day4.md`). Days 5–7 (pytest suite, eval suite, deploy) are the upcoming work.

## Common Commands

All commands run from the repo root with the venv active (`venv/Scripts/activate` on Windows / `source venv/bin/activate` elsewhere).

```bash
# Install
pip install -r requirements.txt

# Apply DB schema (Neon Postgres, requires DATABASE_URL in .env)
alembic upgrade head

# Run the full debate in the terminal (Day 2 CLI)
python run_cli.py
python run_cli.py --topic "Social media should be regulated as a public utility" --rounds 5

# Verify graph topology + round counting with a FakeLLM (no API calls)
python dry_run.py

# Run the FastAPI server (Day 3)
python run_api.py
python run_api.py --port 9000 --reload
# Equivalent: python -m debate_gpt api --port 8000

# Frontend (Day 4) — run from frontend/ with venv active on the backend
cd frontend
npm install
npm run dev          # http://localhost:5173
npm run build        # production bundle in frontend/dist/
```

Manual end-to-end smoke procedures live in `tests/manual_day3.md` (curl) and `tests/manual_day4.md` (frontend). No `pytest` suite exists yet — Day 5 will add `tests/unit/`, `tests/integration/`, `tests/evals/`.

## Environment

A `.env` at the repo root is required. Copy `.env.example` to `.env` and fill in real keys. Required: `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `DATABASE_URL`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`. Optional: `CORS_ORIGINS` (default `*`), `LOKI_ENABLED`/`LOKI_URL`, `LOG_LEVEL`, `MAX_ROUNDS` (2–5, default 3).

The package is importable as `src/` (sys.path is patched by the three launcher scripts) — no `pip install -e .` needed for local dev.

## Code Architecture

### Three entry points (all at repo root)

- `run_cli.py` — argparse-driven end-to-end debate, prints transcript. Drives the LangGraph graph directly via `graph.invoke()`; no streaming, no DB. Used for Day 2 development.
- `run_api.py` — thin wrapper around `python -m debate_gpt api`. Starts uvicorn with the FastAPI app factory.
- `dry_run.py` — Wires the graph manually with a `FakeLLM` stub (cycles pro/con/judge by inspecting system-prompt substrings) to assert 3 rounds → 6 messages → 3 scorecards → `final round=4`. No network calls.

### Module map (`src/debate_gpt/`)

| Module | Responsibility |
|---|---|
| `state.py` | `DebateState` TypedDict. `messages` uses `add_messages` reducer; `round_scores` uses list-concat; `round` is 1-indexed. |
| `prompts.py` | Pro/Con/Judge system + user messages. Judge labels arguments as "Speaker A"/"Speaker B" — never "Pro"/"Con" — to mitigate position-label bias. |
| `schemas.py` | `RoundScore` Pydantic: 6 int scores 0–10, `round_winner ∈ {A, B, tie}`, bounded `reasoning`. `extra="forbid"`, with a `mode="before"` validator that coerces string/float ints but rejects bools. |
| `agents.py` | `build_llms()` (Groq allam-2-7b Pro, Groq llama-3.1-8b-instant Con, OpenRouter `openai/gpt-oss-120b` Judge) and node factories `make_pro_node` / `make_con_node` / `make_judge_node`. **Judge node swaps A/B labels on even rounds** (`swap = state["round"] % 2 == 0`) and translates the winner back to pro/con. |
| `verdict.py` | Pure functions: `pro_total_for_round`, `con_total_for_round` (swap-aware), `tally(round_scores)` summing per-round `pro_score`/`con_score` (set by the judge node). |
| `graph.py` | `StateGraph` wiring. Topology: `START → pro → con → judge → (conditional)`. Conditional edge: `should_continue` loops while `state["round"] <= state["max_rounds"]`; exits to `END` after the final round (judge increments round to N+1). |
| `runtime.py` | Day 3 background-task runner. Drives the graph round-by-round (not via `graph.stream()`) so it can XADD tokens to Upstash Redis between LLM chunks. Emits per-round `pro_token* → con_token* → judge_score` then a final `verdict` event, then calls `db.complete_debate_sync` to persist rounds + final winner. |
| `redis_stream.py` | Sync `httpx.Client` wrapper around Upstash REST commands (`XADD`, `XRANGE`, `XLEN`, `DEL`, `PING`). Stream key shape: `debate:stream:{session_id}`. |
| `db.py` | asyncpg pool (lazy-init, min 1 / max 5, 2s timeout) and CRUD helpers. `create_debate` accepts an explicit `debate_id` so the API's returned `session_id` matches the row PK. `complete_debate` writes one `debate_rounds` row per round in a single transaction. `delete_debate` relies on `ON DELETE CASCADE` (see migration `0001_init.py`). The `_sync` helpers (`create_debate_sync`, `complete_debate_sync`, `fail_debate_sync`) spin up a one-shot `asyncio.run` for the BackgroundTasks thread. |
| `api.py` | FastAPI factory `create_app()`. Six routes: `POST /debate/start` (201, creates DB row, kicks background task), `GET /debate/{id}/stream` (SSE polls Upstash `XRANGE` every 200ms, supports `Last-Event-ID` resume via exclusive-range cursor `(id`), `GET /debate/{id}/result`, `GET /debates?page=N`, `DELETE /debate/{id}` (cascade DB + Redis cleanup), `GET /health` (delegated to `observability/health.py`). |
| `observability/logging.py` | loguru with three sinks: colored console (always), JSON file `logs/debate-gpt.jsonl` (always), async Loki worker (gated on `LOKI_ENABLED=true`). Stdlib loggers (uvicorn, fastapi, asyncpg, httpx) are intercepted via the standard loguru `InterceptHandler` recipe. |
| `observability/middleware.py` | `RequestLoggingMiddleware`: generates/echoes `X-Request-ID`, sets `request_id` / `trace_id` / `session_id` via `logger.contextualize` so every nested log line inherits them. |
| `observability/health.py` | `/health` route — pings Redis + Postgres in parallel, returns 200/503 + per-dep status + latency_ms. |
| `__main__.py` | `python -m debate_gpt api` launcher (argparse for `--host`/`--port`/`--reload`/`--log-level`). |

### Request flow for a live debate

1. `POST /debate/start` → `db.create_debate(session_id)` (row in `pending` state) → `BackgroundTasks.add_task(run_debate_streaming, …)` → 201.
2. Client opens `GET /debate/{id}/stream` → SSE generator polls `redis_stream.xrange(id, cursor)` every 200ms, yields `id: <stream-id>\ndata: <json>\n\n` for each new entry, closes after the `verdict` event.
3. Background task: pro streams → con streams → judge calls → loop N times → `tally()` → `db.complete_debate_sync`.
4. Client polls (or fetches) `GET /debate/{id}/result` for the persisted transcript.

### Bias mitigation invariant

The judge **never sees the words "Pro" or "Con"**. `agents.make_judge_node` flips which argument is Speaker A on even rounds (`swap = round % 2 == 0`), then `_translate_winner` maps the A/B verdict back. The `verdict.py` totals use `swap` to pick the right speaker's scores. Day 6's eval suite compares scores across swaps to detect position-label bias (threshold: delta < ±1.0).

### Streaming details

- LLM streaming: each `*_node` calls `_stream_and_collect` which flushes in ~50-char chunks via the injected `ChunkSink` (`runtime._xadd_text`).
- The runtime's sink is the XADD wrapper; tests pass `None` and get `llm.invoke()` instead (no streaming cost in unit tests).
- SSE handler **polls** Upstash `XRANGE` every 200ms (Upstash REST does not support `SUBSCRIBE`, so push-based SSE is not possible — see PRD §3.2 "Architecture Note"). Exclusive cursor `(<id>` resumes from strictly-after the last delivered id.

## Database

Postgres schema is in `migrations/versions/0001_init.py` (raw SQL via `op.execute()`, no SQLAlchemy model). Two tables: `debates` (id, topic, position_pro, position_con, status, winner, timestamps) and `debate_rounds` (id, debate_id FK ON DELETE CASCADE, round_number, pro_argument, con_argument, judge_scores JSONB, round_winner, created_at). `migrations/env.py` rewrites asyncpg DSNs to psycopg2 for alembic.

To create a fresh schema: `alembic upgrade head`. To teardown: `alembic downgrade base`.

## Conventions

- **Module-level sys.path hack:** the three launchers (`run_cli.py`, `run_api.py`, `dry_run.py`) and `__main__.py` all `sys.path.insert(0, "src")` so the package imports without `pip install -e .`. Keep that pattern in any new top-level launcher script.
- **No pytest yet:** when adding tests (Day 5), create `tests/unit/`, `tests/integration/`, `tests/evals/` per PRD §9.1. Mock LLMs by passing `FakeLLM` to `build_graph(llms=fake)` or by using `make_*_node(fake_llm)` directly (see `dry_run.py` for the pattern).
- **Path style:** this repo runs on Windows. Use `pathlib.Path` and forward slashes in code; bash here is Git Bash, so `find … -name "*.py"` works.
- **Sync helpers for background tasks:** the FastAPI BackgroundTasks runs sync callables in a thread pool. Any DB work in the runtime must go through the `*_sync` wrappers in `db.py` (which spin up `asyncio.run`), not the async ones directly.
- **No silent failure on Redis/DB outages in critical paths:** the `/health` endpoint surfaces dependency state, the runtime `except` blocks `db.fail_debate_sync`, and the SSE handler yields whatever it can. Don't refactor that without updating the `/health` contract.
- **Don't expose position labels to the judge:** any change to `prompts.py` or `agents.make_judge_node` must preserve the Speaker A/B abstraction. The eval suite assumes this.

## Day-by-day deliverables (from PRD §11, for context)

Days 1–3 are done (graph, judge, API/DB/observability). Day 4 is in progress (frontend scaffolding in `frontend/`, smoke test in `tests/manual_day4.md`). Remaining:
- **Day 4** React frontend — wire `SessionSidebar`, `RoundCard`, `JudgeScorecard`, `VerdictBanner`, delete flow to the Day 3 API.
- **Day 5** pytest unit + integration suite with mocked LLMs.
- **Day 6** Eval suite (judge consistency, position-bias, schema compliance, argument quality) → `eval_results.csv`.
- **Day 7** Multi-stage Dockerfile (builder + runtime, non-root), Railway/Render deploy, Vercel frontend, demo video.

## Progress Tracking
Maintain PROGRESS.md at the project root continuously while working on any 
sprint day:
- Update it after completing each meaningful sub-task (not after every 
  single file edit — after a logical unit of work, like "one test file 
  written and passing")
- Structure: DONE / IN PROGRESS / NOT STARTED, matching the current 
  sprint day's deliverables from docs/PRD.md Section 11
- Before starting a new sub-task, mark the previous one DONE and the new 
  one IN PROGRESS with a one-line note on what's next
- If a task fails or gets interrupted mid-way, note exactly where it 
  stopped and why, so work can resume without re-diagnosing from scratch
- Never let PROGRESS.md go stale for more than one sub-task at a time — 
  it should always reflect the true current state, not the plan