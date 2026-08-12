# Tally Live Entity Dashboard

Built per the phased loop in `00_MASTER_BUILD_PROMPT.md`. All phases (0–6)
are code-complete and pass their offline/simulated verification. **Phases
0, 2, and 3 additionally require a run against your real, open Tally
instance** — that part could not be done in this environment (no Tally
installed here). See "What still needs your real Tally" below.

## Setup

```
cd backend
python -m pip install -r requirements.txt

cd ../frontend
npm install
npm run build
```

The frontend is a React app (Vite) — `npm run build` produces `frontend/dist`,
which `main.py` serves. Run `npm run build` again after any frontend change;
`install_task.ps1` (below) does this automatically. `npm run dev` (from
`frontend/`) runs a hot-reload dev server on its own port with `/api`
proxied to the backend, if you're actively editing the frontend.

Edit `backend/config.yaml` — at minimum set `tally.company_name`. Defaults
assume Tally is on `localhost:9000` (Gateway of Tally > F1 Help > Settings
> Connectivity > Client/Server configuration — enable the HTTP-XML server,
port 9000).

## Run (manual, foreground)

```
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8731
```

Open http://127.0.0.1:8731/ — the dashboard is served from `frontend/` by
the same server. A background sync loop starts automatically with the
server (`main.py`'s lifespan) and polls every `polling.interval_minutes`
(config.yaml, default 5). It's silent when Tally is closed — just writes
an offline snapshot and waits for the next tick — and picks up real data
again on the first poll after Tally is opened, no restart needed. The
"Refresh now" button / `POST /api/refresh` trigger an immediate sync on
top of that, same code path.

`GET /api/health` returns `{status, database_ok, tally_reachable,
last_synced_at}` — a cheap check for whether the server is actually up and
answering, separate from whether Tally itself is reachable.

## Run automatically on every login (recommended)

Registers a Windows Task Scheduler task that starts the dashboard hidden
(no console window) at logon and restarts it if it ever crashes. No
third-party software installed — uses the Task Scheduler built into
Windows.

```
cd backend
powershell -ExecutionPolicy Bypass -File install_task.ps1
```

That's it — dashboard is now always at `http://127.0.0.1:8731/` from the
next logon onward (it also starts it immediately this time). It sits
quietly if Tally isn't open and starts syncing on its own once you open
Tally. Logs go to `backend/server.log` (nothing prints to a console since
it runs headless via `pythonw.exe`).

Useful commands:

```
Get-ScheduledTask -TaskName TallyTracker | Get-ScheduledTaskInfo   # status
Stop-ScheduledTask -TaskName TallyTracker                          # stop now
```

To remove it entirely:

```
cd backend
powershell -ExecutionPolicy Bypass -File uninstall_task.ps1
```

## What still needs your real Tally

Per the Master Prompt, phases that touch live Tally can only be fully
verified against your actual install:

1. **Phase 0** — `python backend/tools/phase0_raw_probe.py` with Tally open.
   Confirms connectivity and lets you note ERP 9 vs. TallyPrime.
2. **Phase 2** — `python backend/verify_live_tally.py` with Tally open.
   `tally_client.py` was written from Tally's documented ad-hoc XML
   Collection pattern (no reference `tally_tracker.py` script existed in
   this project to adapt from), so a few tags are informed guesses most
   likely to need adjusting against your data — see the "TAGS MOST LIKELY
   TO NEED ADJUSTMENT" note at the top of that file. If a fetch function
   returns empty/wrong values, set `TALLY_CLIENT_DEBUG=1` and re-run to
   see Tally's actual raw XML, then fix the tag lookup in that one file.
3. **Phase 3** — once Phase 2 is clean, run the poll loop 3x with nothing
   changed in Tally, then once more after a real edit, and confirm the
   row-count / single-change-row behavior per the Master Prompt's
   checklist (the same logic is already proven offline by
   `test_poller.py` against fake data — this step proves the real XML
   parsing feeds it correctly).

## Automated tests (all runnable now, no Tally needed)

```
cd backend
python -m pip install -r requirements.txt   # includes pytest
python -m pytest        # runs test_db.py, test_poller.py, test_api.py
```

These also run in CI on every push (`.github/workflows/ci.yml`), alongside
a frontend build check. `verify_live_tally.py` needs a real, open Tally so
it isn't part of the automated suite — run it manually (see above).

## Backups

Every poll cycle takes one SQLite backup per calendar day into
`backend/backups/` (no-op once today's backup already exists), keeping the
last 14. A backup is also taken automatically right before any future
schema migration runs against an existing database — see
`db.py`'s `_MIGRATIONS` / `init_db()`. To restore, stop the server, copy a
`backend/backups/tally-daily-*.db.bak` file over `backend/tally.db`, and
restart.

## Schema changes

`db.py` versions the schema (`schema_version` table) instead of editing
`CREATE TABLE` statements in place. To change the schema, append a new
`(version, description, sql)` tuple to `_MIGRATIONS` in `db.py` — every
existing install picks it up automatically on next start (backup-first,
per above), no manual `ALTER TABLE` required.

## Layout

```
backend/
  tools/
    phase0_raw_probe.py     # Phase 0 - throwaway connectivity check
    seed_demo.py            # fake data for previewing the UI without Tally
  db.py                     # Phase 1 - schema, upserts, dedup enforcement
  test_db.py
  tally_client.py            # Phase 2 - the only file that knows Tally's XML tags
  verify_live_tally.py       # manual check against a real, open Tally (not pytest)
  diff_engine.py             # Phase 3 - compares snapshots, writes `changes`
  poller.py                  # Phase 3 - the one sync loop (timer + /api/refresh)
  test_poller.py
  main.py                    # Phase 4 - FastAPI REST API + SSE live-update stream
  test_api.py
  bank_reconciliation.py     # bank statement upload/parsing + fuzzy match scoring
  notifier.py                 # Phase 6 - desktop notifications, one per change
  config.py / config.yaml     # Phase 6 - single source of truth for settings
frontend/
  src/                       # React app (Vite) - components, api client, hooks
  dist/                      # build output, served by main.py (git-ignored)
  package.json / vite.config.js
```

## Non-negotiable rule this build follows throughout

Every write to `entities` / `bills` / `stock_items` is a single
`INSERT ... ON CONFLICT (natural_key) DO UPDATE ...`, never a two-step
"check then insert." Natural keys carry real SQLite `UNIQUE` constraints.
`followups` is never touched by the sync path. See
`01_ARCHITECTURE_AND_DATA_MODEL.md` for the full rationale.
