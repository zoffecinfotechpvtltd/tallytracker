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
```

Edit `backend/config.yaml` — at minimum set `tally.company_name`. Defaults
assume Tally is on `localhost:9000` (Gateway of Tally > F1 Help > Settings
> Connectivity > Client/Server configuration — enable the HTTP-XML server,
port 9000).

## Run (manual, foreground)

```
cd backend
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Open http://127.0.0.1:8731/ — the dashboard is served from `frontend/` by
the same server. A background sync loop starts automatically with the
server (`main.py`'s lifespan) and polls every `polling.interval_minutes`
(config.yaml, default 5). It's silent when Tally is closed — just writes
an offline snapshot and waits for the next tick — and picks up real data
again on the first poll after Tally is opened, no restart needed. The
"Refresh now" button / `POST /api/refresh` trigger an immediate sync on
top of that, same code path.

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

1. **Phase 0** — `python backend/phase0_raw_probe.py` with Tally open.
   Confirms connectivity and lets you note ERP 9 vs. TallyPrime.
2. **Phase 2** — `python backend/test_tally_client.py` with Tally open.
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

## Verification scripts (all runnable now, no Tally needed)

```
cd backend
python test_db.py       # Phase 1 - schema + dedup upserts
python test_poller.py   # Phase 3 - sync/diff idempotency, offline fake Tally
python test_api.py      # Phase 4 - API contracts, offline fake Tally
```

`test_tally_client.py` needs a real, open Tally (see above).

## Layout

```
backend/
  phase0_raw_probe.py    # Phase 0 - throwaway connectivity check
  db.py                  # Phase 1 - schema, upserts, dedup enforcement
  test_db.py
  tally_client.py         # Phase 2 - the only file that knows Tally's XML tags
  test_tally_client.py
  diff_engine.py          # Phase 3 - compares snapshots, writes `changes`
  poller.py               # Phase 3 - the one sync loop (timer + /api/refresh)
  test_poller.py
  main.py                 # Phase 4 - FastAPI REST API
  test_api.py
  notifier.py              # Phase 6 - desktop notifications, one per change
  config.py / config.yaml  # Phase 6 - single source of truth for settings
frontend/
  index.html / style.css / app.js   # Phase 5 - dashboard (no build step)
```

## Non-negotiable rule this build follows throughout

Every write to `entities` / `bills` / `stock_items` is a single
`INSERT ... ON CONFLICT (natural_key) DO UPDATE ...`, never a two-step
"check then insert." Natural keys carry real SQLite `UNIQUE` constraints.
`followups` is never touched by the sync path. See
`01_ARCHITECTURE_AND_DATA_MODEL.md` for the full rationale.
