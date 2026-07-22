# Debate-GPT

Multi-agent AI debate platform. Two LLM agents argue opposing sides of a user-supplied topic, a third (more powerful) model scores each round as an impartial judge, and a final verdict is declared.

The full PRD lives in [`PRD.md`](PRD.md) — read it before changing architecture.

## Quick start

```bash
# 1. Install
python -m venv venv
source venv/bin/activate          # POSIX
venv\Scripts\activate             # Windows
pip install -r requirements.txt

# 2. Configure
cp .env.example .env              # then fill in real keys

# 3. Apply DB schema (Neon Postgres)
alembic upgrade head

# 4. Run the API
python run_api.py                 # http://localhost:8000
```

## Running the test suite (Day 5)

The pytest suite runs **fully offline** — no real LLM, Redis, or Postgres calls. `tests/conftest.py` injects in-memory fakes at every external I/O boundary.

```bash
# Full suite with coverage (preferred)
make test
# Equivalent: pytest --cov=src/debate_gpt --cov-report=term-missing tests/

# Just unit tests (skip integration)
make test-unit
# Equivalent: pytest tests/unit/ -m "not integration"

# Just integration tests
make test-integration
# Equivalent: pytest tests/integration/

# Plain pytest (no coverage)
python -m pytest tests/
```

The `make test` target reports a per-file coverage table via `term-missing`. Day 5 is done when overall line coverage is **> 80%**. See `PROGRESS.md` for the live status.

## Test layout

| Directory | Contents |
|---|---|
| `tests/unit/` | Pure-Python tests: state, schemas, prompts, verdict aggregation, redis_stream wrapper, session_utils. |
| `tests/integration/` | Full FastAPI app via `httpx.AsyncClient` + `ASGITransport`. Drives every route (`POST /debate/start`, `GET /debate/{id}/stream`, `GET /debate/{id}/result`, `GET /debates`, `DELETE /debate/{id}`, `GET /health`) with the in-memory Redis + DB fakes. |
| `tests/evals/` | Bare scaffold for Day 6 (real-LLM eval suite: judge consistency, position-bias, schema compliance, argument quality). Not collected by default. |

`pyproject.toml` configures pytest with `asyncio_mode = "auto"` and registers the `integration` marker, so async tests are picked up without an explicit decorator.

## Day-by-day status

See [`PROGRESS.md`](PROGRESS.md) for the live sprint tracker (Days 1–7, per PRD §11).

## Frontend

The Day-4 React frontend lives in `frontend/`. See `tests/manual_day4.md` for the end-to-end smoke procedure.

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```
