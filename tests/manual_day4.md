# Debate-GPT — Day 4 Manual Test (React Frontend)

This procedure verifies the Day 4 React frontend end-to-end against the
live Day 3 FastAPI backend. It mirrors the structure of
`manual_day3.md`. All commands assume Windows + Git Bash and that your
working directory is the repo root (`D:\Agents1\debate-gpt`).

## 0. Prerequisites

- Python venv active and backend deps installed (`pip install -r requirements.txt`).
- DB schema applied (`alembic upgrade head`).
- Backend `.env` populated (see Day 3 procedure).
- `CORS_ORIGINS=http://localhost:5173` is set in `.env` (already
  present in the committed `.env.example`).
- Node.js 18+ installed (`node -v` should print ≥ v18).

## 1. Start the backend (Day 3)

```bash
cd /d/Agents1/debate-gpt
source venv/Scripts/activate
python run_api.py
```

Expected: `Uvicorn running on http://0.0.0.0:8000`. Health check:

```bash
curl -s http://localhost:8000/health
```

Expected: JSON with `status: "ok"` (HTTP 200). If you see `503`, fix
the dependency before continuing — see Day 3 troubleshooting.

## 2. Install + start the frontend (Day 4)

In a **second** terminal:

```bash
cd /d/Agents1/debate-gpt/frontend
npm install        # first time only, ~5 minutes
cp .env.example .env.local   # first time only
npm run dev
```

Expected last line: `Local: http://localhost:5173/`. Open the URL in a
browser.

## 3. Empty-state sanity

You should see:

- Left sidebar: title "Debate-GPT" and the text "No past debates yet."
- Main panel: heading "Start a debate", short description, then a form
  with a topic textarea, a Persona dropdown (default "Oxford Debater",
  note "(UI only — Day 6 wires it)"), a Rounds dropdown (default 3),
  and a "Start debate" button.

Open DevTools → Console. There should be **no errors or warnings** (a
React Router 6 future-flag warning is fine; otherwise silent).

## 4. Start a live debate

1. Type a topic of 3–500 characters in the textarea, e.g.:
   `Universal basic income should be adopted worldwide`.
2. Leave persona on "Oxford Debater", rounds on 3.
3. Click **Start debate**.

Expected:

- The URL changes to `/debate/<uuid>`.
- A "Round 1" card appears.
- **Pro** text begins streaming into the left column (~50 chars at a
  time).
- Once Pro finishes, **Con** text streams into the right column.
- After both finish, a `JudgeScorecard` appears below the two columns
  with three rubric bars (Logic / Evidence / Persuasion) for each
  side, the round's `pro_score` / `con_score` totals, and a winner
  chip ("Pro wins" / "Con wins" / "Tie").
- Round 2 and Round 3 follow the same pattern.

## 5. Scorecard interactions

- Click anywhere on a scorecard. The judge's reasoning text should
  expand below the bars. Click again to collapse.
- Once a scorecard appears, a "Hide arguments" / "Show arguments"
  toggle appears in the round's header. Click it to collapse the
  Pro/Con columns and focus on the score.

## 6. Verdict

After the final round's scorecard, expect a full-width dark indigo
banner (or slate, for a tie) at the bottom of the page showing:

- "Pro wins the debate" (or "Con wins the debate" / "It's a tie") in
  large text.
- Two tiles: "Pro total" and "Con total", with cumulative numbers.
- A "Trace link: coming soon" line (deliberately disabled — the SSE
  verdict event does not include a `trace_id`; Day 6 will wire it).

The "Streaming…" indicator should disappear once the verdict arrives.

## 7. Sidebar history

Navigate back to `/` (click the "Debate-GPT" link in the sidebar
header, or the browser back button).

Expected:

- The sidebar now lists your just-completed debate at the top with:
  - Truncated topic text (hover shows full topic via `title=`).
  - A winner chip ("pro" / "con" / "tie").
  - A date in local format.
  - On hover, a 🗑 icon appears on the right.

## 8. Click into a past debate

Click on the row for the past debate (not the trash icon).

Expected:

- The URL changes to `/debate/<uuid>`.
- The page renders the persisted transcript (no live streaming — the
  SSE stream is no longer alive for a completed debate, so the hook
  loads the topic from `GET /debate/{id}/result`).

The "Streaming…" indicator may briefly show until the hook sees the
stream close. Round cards and verdict should still appear correctly.

## 9. Optimistic delete

1. Hover over a past-debate row. The 🗑 icon appears.
2. Click it.

Expected:

- The row disappears **immediately** (optimistic).
- No network delay; the row is gone before the request returns.
- No page navigation (the click is `stopPropagation`-ed).

Verify rollback on failure:

1. Temporarily point the frontend at a dead backend. In
   `frontend/.env.local`, set `VITE_API_BASE_URL=http://localhost:9999`
   and restart `npm run dev`.
2. Navigate to `/` and try the trash icon.
3. Expect: the row disappears, then reappears within ~2 seconds with a
   small red "Delete failed: …" banner at the top of the sidebar.
4. Restore `.env.local` to `http://localhost:8000` and restart the
   dev server.

## 10. SSE shape in DevTools

1. Open DevTools → Network tab. Filter by `EventStream` (or look for
   requests with type `eventsource`).
2. Start a new debate.
3. Click the SSE request for `/debate/<uuid>/stream`.
4. In the "EventStream" tab, you should see entries in this order:
   - Many `message` events with `event: "pro_token"` and `event: "con_token"` (plain text content).
   - Three `message` events with `event: "judge_score"` — each with a JSON-stringified `content`.
   - One `message` event with `event: "verdict"` — JSON-stringified `{pro_total, con_total, winner}`.
   - One named `done` event with empty `data`.
   - The connection closes.

## 11. Error display

Force a backend error:

1. Stop the backend (`Ctrl-C` in its terminal).
2. In the frontend, navigate to `/` and try to start a new debate.

Expected:

- An inline red error message appears in the form ("500 Internal
  Server Error: database unavailable" or similar).
- The page does not crash or show a blank screen.
- The "Start debate" button re-enables (the `submitting` state resets
  in the `finally` block).

3. Restart the backend and confirm normal operation resumes.

## 12. Production build (optional sanity)

```bash
cd /d/Agents1/debate-gpt/frontend
npm run build
```

Expected: 0 errors, output in `frontend/dist/`. Bundle size around
180 KB JS / 16 KB CSS (gzipped: ~58 KB / ~4 KB).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Browser shows blank page, console: "Failed to fetch" | Backend not running or CORS | `curl localhost:8000/health`; check `CORS_ORIGINS` in `.env`; restart backend |
| "Connection closed before the debate finished" banner | Backend died mid-debate | Check backend terminal for traceback; restart `python run_api.py` |
| `pro_token` text appears garbled / fragmented | Normal — chunks are ~50 chars | No action needed |
| Trash icon doesn't appear | Hover state CSS | Move the mouse over the row; the icon is `opacity-0 group-hover:opacity-100` |
| `npm run dev` says "Port 5173 is already in use" | Another process is on 5173 | Set `server.port` in `vite.config.js` to 5174 and update `CORS_ORIGINS` to match |
| Vite log shows CSS errors about `@tailwindcss/vite` | Stale install | `rm -rf frontend/node_modules frontend/package-lock.json && npm install` |
| `npm install` hangs on Windows | Network / proxy | Verify `npm config get registry`; retry with `npm install --no-audit --no-fund` |
| Build OK but page is unstyled | Tailwind plugin didn't load | Verify `vite.config.js` imports `tailwindcss from "@tailwindcss/vite"` and that `@tailwindcss/vite` is in `devDependencies` |
| `pickProSide` mismatch (bars don't match the totals shown) | Backend translation bug (not frontend) | Compare `pro_score` to the sum of A's and B's criteria; if not equal, log a backend issue and Day 6 will investigate |

## What this manual test does NOT cover (out of scope for Day 4)

- Persona backend wiring (Day 6)
- LangSmith trace link in the verdict banner (Day 6)
- pytest suite for the frontend (Day 5)
- Docker / deployment (Day 7)
- Advanced error handling / retry policies
