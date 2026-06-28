# PRODUCT REQUIREMENTS DOCUMENT — Debate-GPT
### Multi-Agent AI Debate Platform

| Field | Value |
|---|---|
| **Version** | v1.0.0 |
| **Status** | Draft — Ready for Review |
| **Author** | Sameer |
| **Date** | June 25, 2026 |
| **Deadline** | 7 days from start |
| **Classification** | Portfolio Project — AI/ML Engineering |

---

## 1. Executive Summary

Debate-GPT is a multi-agent AI platform where two large language models argue opposing sides of any user-defined topic, while a third, more powerful model acts as an impartial judge scoring each round. The system produces a structured debate transcript, per-round scorecards, and a final verdict — all streamed live to the user interface.

This project is designed to be completed in one week (7 days) and serves as a portfolio-grade demonstration of multi-agent orchestration, LLM-as-Judge evaluation methodology, structured output enforcement, SSE streaming, and full-stack AI engineering.

> **Core Value Proposition:** Unlike "chat with a document" or "summarize text" tools, Debate-GPT demonstrates adversarial reasoning between agents, judge consistency evaluation, and bias mitigation — skills directly aligned with production AI/ML engineering.

---

## 2. Problem Statement & Goals

### 2.1 Problem Statement
Evaluating the quality of LLM reasoning is a fundamental challenge in production AI systems. Current portfolio projects often demonstrate retrieval, generation, or classification in isolation. There is a gap in projects that show adversarial multi-agent interaction, structured judgment, and measurable consistency.

### 2.2 Primary Goals
- Demonstrate LangGraph-based multi-agent orchestration with conditional state transitions
- Implement a rubric-driven LLM-as-Judge system with measurable consistency and bias mitigation
- Build a production-quality full-stack application using a modern AI engineering stack
- Generate portfolio artifacts: eval report, architecture documentation, live demo
- Complete within a 7-day sprint window

### 2.3 Non-Goals
- Real-time multi-user collaboration or multiplayer debate (out of scope for v1)
- Voice/audio input or text-to-speech output
- Fine-tuning or custom model training
- Mobile-native application (responsive web only)

---

## 3. System Architecture

### 3.1 High-Level Architecture

| Layer | Component | Technology | Responsibility |
|---|---|---|---|
| Presentation | Debate UI | React + Vite + Tailwind | Renders live debate, scores, history sidebar, verdict |
| API Gateway | REST + SSE Server | FastAPI + Uvicorn | Session management, streaming endpoints, auth middleware |
| Orchestration | Debate Graph | LangGraph + LangSmith | State machine, round loop, conditional routing, tracing |
| Agent Layer | Pro / Con / Judge | Groq + OpenRouter APIs | LLM inference, structured output, persona enforcement |
| Persistence | Cache + DB | Upstash Redis + Neon | Session state caching, SSE event stream (Redis Streams), debate history, scores storage |

### 3.2 Debate Flow — Step by Step

1. User submits topic via React frontend → `POST /debate/start`
2. FastAPI creates a session ID, stores initial state in Upstash Redis, returns session ID to client
3. Client opens SSE connection to `GET /debate/{id}/stream`
4. FastAPI kicks off LangGraph debate graph as a background task
5. Graph executes Round 1: `pro_node → con_node → judge_node`
6. Each node streams its output token-by-token by writing to a Redis Stream (`XADD`) keyed by session ID; the SSE endpoint polls the stream (`XRANGE` since last-seen ID) and forwards new entries to the client
7. Judge node scores Round 1 using structured JSON output (logic / evidence / persuasion)
8. LangGraph conditional edge checks: if round < max_rounds → loop to pro_node, else → verdict_node
9. Rounds 2 and 3 execute identically
10. `verdict_node` tallies total scores, declares winner, writes full record to Neon PostgreSQL
11. SSE stream closes; client renders final verdict panel

> **Architecture Note — Streams, Not Pub/Sub:** Upstash Redis's REST API does not support `SUBSCRIBE` (it requires a persistent connection, which a stateless REST call cannot hold), so a "Redis pub/sub" design will not deliver events. Nodes instead append tokens to a Redis Stream (`XADD`) keyed by session ID, and the SSE handler polls new entries with `XRANGE` since the last-seen ID — the same pattern already validated in the AXIS project.

### 3.3 LangGraph State Definition

```python
class DebateState(TypedDict):
    session_id:    str
    topic:         str
    position_pro:  str      # "For: X"
    position_con:  str      # "Against: X"
    round:         int      # current round (1-indexed)
    max_rounds:    int      # default 3
    messages:      list[Message]   # full transcript
    round_scores:  list[RoundScore]
    winner:        str | None
    trace_id:      str      # LangSmith trace ID
```

### 3.4 Agent Specifications

| Agent | Model | Temperature | Role | Output |
|---|---|---|---|---|
| Pro | allam-2-7b (Groq) | 0.9 | Argue FOR topic | Free text, ~200 words |
| Con | llama-3.1-8b-instant (Groq) | 0.9 | Argue AGAINST topic | Free text, ~200 words |
| Judge | openai/gpt-oss-120b (OpenRouter) | 0.2 | Score each round | Structured JSON |

> **Bias Mitigation Note:** The Judge agent receives arguments labeled "Speaker A" and "Speaker B" — never "Pro" or "Con". This prevents position-label bias. A bias test is included in the eval suite: the same two arguments are submitted with labels swapped; scores should not change by more than ±1 point.

### 3.5 Judge Structured Output Schema

```python
class RoundScore(BaseModel):
    speaker_a_logic:      int  # 0-10
    speaker_a_evidence:   int  # 0-10
    speaker_a_persuasion: int  # 0-10
    speaker_b_logic:      int  # 0-10
    speaker_b_evidence:   int  # 0-10
    speaker_b_persuasion: int  # 0-10
    round_winner:         Literal["A", "B", "tie"]
    reasoning:            str  # 1-2 sentences
```

---

## 4. Technology Stack

| Category | Technology | Version / Config | Purpose |
|---|---|---|---|
| Frontend | React | ^18 | UI framework |
| | Vite | ^5 | Build tool, dev server |
| | Tailwind CSS | ^3 | Utility-first styling |
| | React Router v6 | ^6 | Client-side routing |
| Backend | FastAPI | ^0.115 | REST API + SSE server |
| | Uvicorn | ASGI worker | Async server, production ASGI |
| | Pydantic v2 | ^2 | Request/response validation, judge schema |
| | python-dotenv | latest | Environment variable management |
| Orchestration | LangGraph | ^0.2 | Debate state machine, conditional edges |
| | LangChain Core | ^0.3 | Message types, prompt templates |
| | LangSmith @traceable | LANGCHAIN_TRACING_V2=true | Trace every node execution, token costs |
| LLM APIs | Groq (Pro + Con) | allam-2-7b, llama-3.1-8b-instant | Fast inference for debater agents |
| | OpenRouter (Judge) | openai/gpt-oss-120b | High-quality structured judgment |
| Persistence | Upstash Redis | REST API (serverless) | Session state, SSE event stream (Redis Streams), short-lived cache |
| | Neon PostgreSQL | Serverless Postgres | Permanent debate history, scores, transcripts |
| | asyncpg / psycopg2 | async driver | Async Postgres connection pool |
| Testing | pytest + pytest-asyncio | ^8 | Unit and integration test runner |
| | httpx | async HTTP client | FastAPI integration test client |
| | pytest-cov | latest | Coverage reporting |
| Infra / DevOps | Docker (multi-stage) | layer caching, non-root | Containerized backend, minimal image size |
| | GitHub Actions | CI/CD pipeline | Lint, test, build, deploy on push |

---

## 5. API Design

### 5.1 REST Endpoints

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| POST | /debate/start | None (v1) | Create new debate session; returns session_id |
| GET | /debate/{id}/stream | None (v1) | SSE stream — yields agent tokens live |
| GET | /debate/{id}/result | None (v1) | Full transcript + scores + winner after completion |
| GET | /debates | None (v1) | List all past debates (paginated, 20 per page) |
| DELETE | /debate/{id} | None (v1) | Delete debate from history (Postgres + Redis cleanup) |
| GET | /health | None | Health check (Redis ping + DB connectivity) |

### 5.2 SSE Event Schema

```
data: {"event": "pro_token",   "round": 1, "content": "The evidence shows..."}
data: {"event": "con_token",   "round": 1, "content": "However, critics..."}
data: {"event": "judge_score", "round": 1, "content": {RoundScore}}
data: {"event": "verdict",     "winner": "pro", "total_scores": {...}}
data: {"event": "error",       "message": "Rate limit exceeded"}
```

---

## 6. Database Schema (Neon PostgreSQL)

```sql
CREATE TABLE debates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic        TEXT NOT NULL,
  position_pro TEXT NOT NULL,
  position_con TEXT NOT NULL,
  status       TEXT DEFAULT 'pending',  -- pending|running|complete|error
  winner       TEXT,                     -- "pro"|"con"|"tie"|NULL
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ
);

CREATE TABLE debate_rounds (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  debate_id      UUID REFERENCES debates(id) ON DELETE CASCADE,
  round_number   INT NOT NULL,
  pro_argument   TEXT NOT NULL,
  con_argument   TEXT NOT NULL,
  judge_scores   JSONB NOT NULL,   -- RoundScore schema
  round_winner   TEXT,
  created_at     TIMESTAMPTZ DEFAULT NOW()
);
```

> **ON DELETE CASCADE:** `debate_rounds` references `debates` with `ON DELETE CASCADE` — deleting a debate via the API removes all associated rounds atomically without requiring application-level cleanup logic.

---

## 7. Frontend Design

### 7.1 Layout
Two-panel layout:
- **Left sidebar (~280px):** session list of past debates with topic, date, winner badge, and a delete button per item
- **Main panel:** active debate view — topic input form, live round cards (Pro left / Con right), judge scorecard, final verdict banner

### 7.2 Key Components

| Component | Description |
|---|---|
| SessionSidebar | Lists all past debates from `GET /debates`. Each item shows topic (truncated), date, winner chip. Trash icon triggers `DELETE /debate/{id}` with optimistic UI update. |
| DebateForm | Input for topic, optional persona selector (Oxford / Academic / Street), round count selector (2–5). Submits to `POST /debate/start`. |
| RoundCard | Two-column card: Pro argument streams on the left, Con argument on the right. Tokens append in real time via SSE. Collapse toggle after round completes. |
| JudgeScorecard | Appears after each round. Animated score bars for Logic, Evidence, Persuasion. Shows round winner chip. Expands judge reasoning on click. |
| VerdictBanner | Full-width banner after all rounds. Shows overall winner, cumulative scores, LangSmith trace link. |

---

## 8. Docker & Containerization

### 8.1 Multi-Stage Dockerfile Strategy

- **Stage 1 (builder):** Uses `python:3.12-slim`. Installs build dependencies, compiles wheels into `/wheels`. Discarded after stage 2.
- **Stage 2 (runtime):** Copies only the compiled wheels. No build tools, no compilers, no pip cache. ~60% smaller final image.

```dockerfile
# Stage 1 — builder
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# Stage 2 — runtime
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir --no-index --find-links /wheels /wheels/*.whl
COPY . .

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### 8.2 Layer Caching Strategy
- `requirements.txt` is copied before application code — dependency layer is only invalidated when requirements change
- `COPY . .` comes last, so code changes do not trigger a full pip reinstall
- `.dockerignore` excludes `__pycache__`, `.git`, `tests/`, `.env`, `node_modules`

---

## 9. Testing Strategy

### 9.1 Test Structure

```
tests/
  unit/
    test_debate_state.py      # DebateState TypedDict validation
    test_judge_schema.py      # RoundScore Pydantic model
    test_score_aggregation.py # Verdict calculation logic
    test_session_utils.py     # Redis key helpers
  integration/
    test_debate_api.py        # Full POST /debate/start → stream → result
    test_delete_debate.py     # DELETE cascade behavior
    test_sse_stream.py        # SSE event ordering and schema
  evals/
    test_judge_consistency.py # Same prompt → score variance < threshold
    test_position_bias.py     # Swapped labels → scores unchanged
    eval_report.py            # Generates CSV eval summary
```

### 9.2 Unit Tests
- Test `DebateState` creation with valid and invalid round counts
- Test `RoundScore` Pydantic validation rejects out-of-range scores (0–10)
- Test verdict aggregation: tie detection, tiebreak logic, winner mapping
- Test Redis key naming conventions and TTL configuration

### 9.3 Integration Tests
Integration tests use `httpx.AsyncClient` with FastAPI's test app. LLM calls are mocked using `pytest-mock` to return deterministic `RoundScore` fixtures — tests remain fast and free.
- `POST /debate/start` returns 201 with valid `session_id`
- `GET /debate/{id}/stream` emits events in correct order: `pro_token → con_token → judge_score → verdict`
- `DELETE /debate/{id}` removes from Postgres and returns 204
- `GET /debates` returns paginated list with correct schema

### 9.4 Eval Suite
The eval suite uses real LLM calls (not mocked) and is run separately from the CI suite. Results are written to `eval_results.csv`.

| Eval Test | Method | Pass Threshold |
|---|---|---|
| Judge consistency | Same argument pair, 5 runs → measure score variance | Std dev < 1.5 per criterion |
| Position bias | Swap Speaker A/B labels, compare scores | Score delta < ±1.0 |
| Schema compliance | 100 judge calls → validate all against RoundScore | 100% valid JSON |
| Argument quality | LLM-as-evaluator scores pro/con coherence | Mean coherence > 7/10 |

---

## 10. LangSmith Tracing

Every LangGraph node is decorated with `@traceable`. The `LANGCHAIN_TRACING_V2=true` environment variable activates automatic trace capture. Each debate session produces one parent trace with three child traces (one per round), each containing the full pro/con/judge node chain.

### 10.1 What Gets Traced
- Input and output of every node (full prompt + completion)
- Token counts and latency per agent call
- LangGraph state transitions and conditional edge evaluations
- Any exceptions or retry events

### 10.2 Trace ID in UI
The LangSmith trace URL is embedded in the VerdictBanner component so users can click through to inspect the full debate trace.

---

## 11. 7-Day Sprint Plan

| Day | Theme | Deliverables | Done When |
|---|---|---|---|
| 1 | Scaffold + LangGraph core | DebateState, 4-node graph, agent prompts, terminal test loop | Full debate runs in CLI |
| 2 | Judge rubric + structured output | RoundScore schema, bias mitigation, 3 manual test debates | Judge returns valid JSON every call |
| 3 | FastAPI + SSE + DB | All 5 API endpoints, SSE streaming, Neon schema, Redis session | curl debate start → SSE events print |
| 4 | React frontend | SessionSidebar, RoundCard, JudgeScorecard, VerdictBanner, delete flow | Live debate renders in browser |
| 5 | Pytest suite | Unit tests (state, schema, aggregation), integration tests (mocked LLMs) | pytest passes, >80% coverage |
| 6 | Evals + polish | Eval suite (consistency, bias), CSV report, persona selector, error handling | Eval report generated |
| 7 | Deploy + submit | Dockerfile, Railway/Render deploy, Vercel frontend, README, demo video | Live URL + GitHub pushed |

---

## 12. Environment Variables

| Variable | Description |
|---|---|
| GROQ_API_KEY | Groq API key for allam-2-7b and llama-3.1-8b-instant |
| OPENROUTER_API_KEY | OpenRouter key for openai/gpt-oss-120b judge |
| UPSTASH_REDIS_REST_URL | Upstash Redis REST endpoint |
| UPSTASH_REDIS_REST_TOKEN | Upstash Redis auth token |
| DATABASE_URL | Neon PostgreSQL connection string (asyncpg format) |
| LANGCHAIN_API_KEY | LangSmith API key |
| LANGCHAIN_TRACING_V2 | Set to "true" to enable LangSmith tracing |
| LANGCHAIN_PROJECT | LangSmith project name (e.g. "debate-gpt") |
| MAX_ROUNDS | Default debate rounds (2–5, default: 3) |
| CORS_ORIGINS | Comma-separated allowed origins for CORS middleware |

---

## 13. Risks & Mitigations

| Risk | Mitigation | Likelihood |
|---|---|---|
| Groq rate limits hit during eval runs | Add exponential backoff + jitter; run evals off-peak | Medium |
| Judge returns invalid JSON | Pydantic validation with fallback retry (max 2 retries) | Low with gpt-oss-120b |
| SSE connection drops mid-debate | Client auto-reconnects; Redis stores partial state for resume | Low |
| Frontend Tailwind config issues (PostCSS) | Use Vite plugin approach; test config on Day 1 | Low (known from prior project) |
| Neon cold-start latency on free tier | Use connection pooling; keep /health warm with 1-min cron | Medium |
| Unauthenticated /debate/start abused, draining LLM API credits | IP-based rate limit (e.g. slowapi) on /debate/start; cap max_rounds server-side regardless of client input | Medium (public URL, no auth by design) |

---

## 14. Success Criteria

### 14.1 Functional
- A complete 3-round debate runs end-to-end in under 60 seconds
- Judge returns valid structured JSON on 100% of calls in integration tests
- Session can be deleted from sidebar and disappears immediately (optimistic update)
- All 5 API endpoints return correct HTTP status codes

### 14.2 Quality
- pytest unit + integration suite passes with > 80% line coverage
- Judge consistency eval: score std dev < 1.5 across 5 identical runs
- Position bias eval: score delta < ±1.0 when Speaker A/B labels are swapped

### 14.3 Portfolio
- README includes architecture diagram, eval findings, and design decisions
- LangSmith trace link visible in VerdictBanner for every completed debate
- Deployed to a live URL (Railway + Vercel)
- 2-minute demo video recorded showing full debate from input to verdict

---
*Confidential — Portfolio Project*