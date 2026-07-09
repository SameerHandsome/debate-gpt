# Day 3 — Manual End-to-End Test

This is the curl flow the user runs to verify the Day 3 wiring.
Recorded here so the procedure is reproducible from a fresh clone.

## 0. Prereqs

`.env` at the repo root must have real values for:

| Variable | Where to get it |
|---|---|
| `GROQ_API_KEY` | https://console.groq.com/keys |
| `OPENROUTER_API_KEY` | https://openrouter.ai/keys |
| `DATABASE_URL` | Neon dashboard → Connection string (asyncpg form) |
| `UPSTASH_REDIS_REST_URL` | Upstash console → REST API section |
| `UPSTASH_REDIS_REST_TOKEN` | Upstash console → REST API section |

Optional:

- `LOKI_ENABLED=true` + `LOKI_URL=https://loki.example/`
- `CORS_ORIGINS=http://localhost:5173` (Vite default)
- `LOG_LEVEL=INFO` (or `DEBUG`)

The `.env.example` is the template — copy to `.env` and fill in real values.

## 1. Apply the schema

```bash
alembic upgrade head
```

Expected: ends with `running upgrade  -> 0001_init, init`. Verify with
Neon's SQL editor:

```sql
SELECT table_name FROM information_schema.tables
 WHERE table_schema='public' ORDER BY table_name;
-- expect: debate_rounds, debates
```

## 2. Start the server

```bash
python run_api.py
# or: python -m src.debate_gpt.__main__
# or: python -m debate_gpt api   (after pip install -e .)
```

Expected console output:

```
HH:MM:SS | INFO | logging configured: level=INFO loki=off
INFO:     Started server process [...]
INFO:     Waiting for application startup.
HH:MM:SS | INFO | app startup complete
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:8000
```

If `LOKI_ENABLED=true`, also expect `loki sink started` (printed by
`start_loki_worker` if you add a log there — currently silent on success).

## 3. Health check

```bash
curl -i http://localhost:8000/health
```

When both deps are up:

```
HTTP/1.1 200 OK
content-type: application/json
x-request-id: <uuid>

{"status":"ok","redis":{"status":"ok","latency_ms":12.3},
                 "postgres":{"status":"ok","latency_ms":8.1}}
```

When either dep is degraded:

```
HTTP/1.1 503 Service Unavailable
{"status":"degraded","redis":{"status":"down",...},"postgres":{...}}
```

## 4. Start a debate

```bash
SID=$(curl -sS -X POST http://localhost:8000/debate/start \
        -H "Content-Type: application/json" \
        -d '{"topic":"Universal basic income should be adopted worldwide","max_rounds":3}' \
        | python -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
echo "session_id=$SID"
```

Expected: a UUID4 string.

## 5. Subscribe to the SSE stream

```bash
curl -N http://localhost:8000/debate/$SID/stream
```

Expected output (a long stream):

```
id: 1700000000000-0
data: {"event":"pro_token","round":1,"content":"The evidence shows..."}

id: 1700000000000-1
data: {"event":"pro_token","round":1,"content":" ..."}

...

id: 1700000000001-3
data: {"event":"judge_score","round":1,"content":{"speaker_a_logic":7,...,"pro_score":18,"con_score":15,"round_winner":"pro"}}

... (3 rounds) ...

id: 1700000000003-9
data: {"event":"verdict","round":0,"content":{"pro_total":48,"con_total":42,"winner":"pro"}}

event: done
data: {}
```

Reconnects: pass the last `id` back via `Last-Event-ID`:

```bash
curl -N -H "Last-Event-ID: 1700000000001-2" http://localhost:8000/debate/$SID/stream
```

The server resumes polling from strictly after that id.

## 6. Fetch the persisted result

```bash
curl -sS http://localhost:8000/debate/$SID/result | python -m json.tool
```

Expected: a `{debate: {...}, rounds: [{...}, ...]}` object. The `debate`
row has `status="complete"`, `winner="pro"|"con"|"tie"`, `completed_at`
set; `rounds` has 3 entries (or 2-5 depending on `max_rounds`) with
`pro_argument`, `con_argument`, `judge_scores` (full JSON), `round_winner`.

## 7. List all debates

```bash
curl -sS 'http://localhost:8000/debates?page=1' | python -m json.tool
```

Expected:

```json
{
  "page": 1,
  "page_size": 20,
  "total": <int>,
  "items": [
    {"id": "<uuid>", "topic": "...", "status": "complete",
     "winner": "pro", "created_at": "...", "completed_at": "..."},
    ...
  ]
}
```

## 8. Delete a debate

```bash
curl -i -X DELETE http://localhost:8000/debate/$SID
```

Expected: `HTTP/1.1 204 No Content`.

After the delete:

- `curl http://localhost:8000/debate/$SID/result` returns 404.
- The `debate_rounds` rows are gone (Postgres `ON DELETE CASCADE`).
- The Redis stream key `debate:stream:$SID` is gone (XADD would now
  start a fresh stream if you reused the id).

## 9. Logs

```bash
tail -f logs/debate-gpt.jsonl | python -c "
import sys, json
for line in sys.stdin:
    rec = json.loads(line)
    r = rec['record']
    extra = r.get('extra', {})
    print(f\"{r['time']['repr']} {r['level']['name']:5} req={extra.get('request_id','-')} trc={extra.get('trace_id','-')} ses={extra.get('session_id','-')} {r['message']}\")
"
```

Expected: every line tagged with `request_id` (UUID4) and `trace_id="-"`
(Day 3 leaves trace_id unwired — Day 6 will populate it from LangSmith).
Outside of a request, `request_id="-"`; inside a request, every nested
log line inherits the same id via `logger.contextualize`.

## 10. The four observability "done-when" checks

1. `logs/debate-gpt.jsonl` has the `request_id` field on every request
   log line — verify by grepping for `"request_id"` and counting
   occurrences vs the curl count.
2. Every response has `X-Request-ID` header (UUID4) — verify with `-i`.
3. `/health` returns 200 when both deps are reachable, 503 when one
   is degraded (test by editing `.env` to a wrong DATABASE_URL).
4. `LOKI_ENABLED=true LOKI_URL=...` (Loki sink) — verify a single
   warning line if Loki is unreachable (`"loki sink push failed: ..."`);
   verify console + JSON sinks continue logging normally.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `asyncio.run() cannot be called from a running event loop` | A `_sync` db helper was called from inside an async route — use the async version. |
| `Status code 204 must not have a response body` | A FastAPI route decorator set `status_code=204` together with a body return — return `Response(status_code=204)` only. |
| `loki sink push failed: <error>` | Loki is down/unreachable — the app still works (console + JSON are always on). |
| `RuntimeError: UPSTASH_REDIS_REST_URL is not set` | `.env` missing the variable; restart the server after editing `.env`. |
| `RuntimeError: DATABASE_URL is not set` | Same. |
| `/debate/{id}/result` returns 404 | The id is wrong, or the debate was deleted (cascade cleanup). |
| SSE closes immediately with no events | The runtime hasn't started yet (the BackgroundTasks task runs **after** the 201 returns). Wait ~200ms and reconnect. |
