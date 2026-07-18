# Debate-GPT Frontend (Day 4)

React + Vite + Tailwind v4 SPA that talks to the Day 3 FastAPI backend.

## Quick start

1. Make sure the backend `.env` includes:
   ```
   CORS_ORIGINS=http://localhost:5173
   ```
   then start the backend: `python run_api.py` (from repo root).
2. From this directory:
   ```
   npm install
   npm run dev
   ```
3. Open http://localhost:5173.

## Config

Copy `.env.example` to `.env.local` and override `VITE_API_BASE_URL` if the
backend runs anywhere other than `http://localhost:8000`.

## Manual end-to-end test

See `../tests/manual_day4.md`.
