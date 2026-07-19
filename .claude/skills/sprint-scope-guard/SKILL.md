---
name: sprint-scope-guard
description: Use automatically before implementing, finalizing, or marking any feature complete in this project — checks the work against the current sprint day's scope in docs/PRD.md Section 11, to prevent implementing features from later days or skipping current-day requirements.
allowed-tools: Read, Grep, Glob
---

# Sprint Scope Guard

Before implementing or declaring any task done:

1. Read `docs/PRD.md` Section 11 (7-Day Sprint Plan) and `PROGRESS.md` if it exists.
2. Identify the current day based on what's already been implemented.
3. Check: does this task belong to the current day, an earlier day, or a later day?
4. If it belongs to a **later day** — stop and flag it. Don't implement it, even if the user's request seems to need it. Say what day it actually belongs to.
5. If it belongs to the **current day** — check the "Done When" column for that day. Confirm nothing required is being skipped.
6. If genuinely ambiguous, ask once rather than assuming.