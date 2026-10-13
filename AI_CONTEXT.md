# The Office App - context for an AI picking this up

Read this first, then `worklog/README.md` (status of every app), then the worklog file
for the app you are working on. Last reviewed: 2026-10-13.

## The business

**Stahlman-England Irrigation (SEI)**, Naples / Southwest Florida. Irrigation service and
installation for communities (HOAs), commercial and residential clients. Jobs, quotes and
invoices live in **Jobber**; accounting in **QuickBooks Online**; mail in **Microsoft 365**
(the shared `PO@stahlman-england.com` mailbox receives vendor paperwork).

People who come up in code and commits:

| Who | Role |
|---|---|
| Simon (simon@stahlman-england.com) | Owner of this repo; runs the office side; signs approved vendor quotes as "Simon Weardon"; gets the Pumps daily email; Receivables sends from his mailbox |
| Beatriz | Office; approves time off |
| Andrea | Office; cc'd on diver emails |
| Christian | Office; pays vendors (Pumps emails him), Snowbirds report recipient |
| Tommy (Wettech, tomm@wettec.biz) | Pump subcontractor |
| Jordan (Gulfshore) | Lake / diver subcontractor |

## The system

One Flask app, **"The Office App"**, deployed on **Railway** from `main`:

- `app.py` (~39k lines) holds the login, dashboard, PO Requests, Community Maintenance,
  Installation, Cash Flow & AR and the Snowbirds SSO bridge.
- Newer apps are their own modules hooked in with `init_<app>(app, ...)`:
  `pumps.py` + `pumps_page.py` + `pump_reports.py`, `receivables.py` + `receivables_page.py`,
  `timeoff.py` (parked). **Put new apps in their own module the same way.**
- `snowbirds/` is R/Shiny, deployed as separate Railway services (Dockerfiles inside).
- Storage: one SQLite database at `$DATA_DIR/po_requests.db` (`DATA_DIR=/data`, a Railway
  volume - see `RAILWAY_SETUP.md`). Each module prefixes its tables (`pump_`, `ar_`, `cf_`, ...).
- Runtime: gunicorn, 2 workers x 4 threads (`railway.json`). Background jobs use APScheduler in
  every worker, so jobs guard themselves with file locks / run-state rows.
- Config is all Railway variables; `env.example` lists them. Never put secrets in code.
- Roles (`session['role']`): `admin`, `office`, `technician` (service or install),
  `property_manager`.

## The apps

| App | Status | Code | Detail |
|---|---|---|---|
| Pumps | Live, most active | `pumps*.py` | [worklog/pumps.md](worklog/pumps.md), `PUMPS_README.md` |
| Receivables | Live, new (Oct 2026) | `receivables*.py` | [worklog/receivables.md](worklog/receivables.md), `RECEIVABLES_README.md` |
| Community Maintenance | Live | `app.py` | [worklog/community.md](worklog/community.md) |
| PO Requests | Live, quiet | `app.py` | [worklog/po.md](worklog/po.md) |
| Snowbirds | Live (R/Shiny) | `snowbirds/` | [worklog/snowbirds.md](worklog/snowbirds.md), `snowbirds/README.md` |
| Installation | Install techs only; office "Coming Soon" | `app.py` | [worklog/installation.md](worklog/installation.md) |
| Cash Flow & AR | Off (`CASHFLOW_ENABLED`) | `app.py` | [worklog/cashflow.md](worklog/cashflow.md) |
| Time-Off Log | Parked | `timeoff.py` | [worklog/timeoff.md](worklog/timeoff.md), `TIMEOFF_README.md` |
| Work Orders | Archived | `archive/workorders/` | [worklog/workorders.md](worklog/workorders.md) |
| Platform (login, admin, deploy) | Live | `app.py`, Railway files | [worklog/platform.md](worklog/platform.md) |

## Rules that are never broken

1. **Nothing is sent to a client by an app.** Quotes and invoices go into Jobber as drafts;
   the office sends them. Pumps enforces this with an allow-list of Jobber mutations
   (`ALLOWED_MUTATIONS` in `pumps.py`); Receivables and Cash Flow only read Jobber.
2. **Never change an amount to make things match.** A mismatch is a to-do for a person.
3. **Never guess a client.** When unsure, the app leaves a to-do.
4. **Nothing is deleted.** Old tables are left in place when an app is switched off or archived.
5. Legal / money steps (Notice of Nonpayment, paying a vendor) always need a person.
6. Secrets only in Railway variables.

## How the work gets done

- Work happens in Claude Code sessions on `claude/<name>` branches, merged into `main` by PR
  (1,268 commits from 2026-01-19 to 2026-10-13). Railway deploys `main`.
- Commit subjects start with the app name and say what changed in the office's words, e.g.
  `Pumps: tick several maintenance visits and mark them notified at once`.
- The owner writes requirements in plain office language; the READMEs and UI copy follow that
  style (short sentences, no jargon, real client names and examples).
- Tests: `pip install -r requirements.txt && python -m unittest tests.test_pumps tests.test_receivables -v`.
  They use a throwaway database and a fake Jobber. Other apps have no tests yet.
- `app.py` builds pages from big Python strings with inline JS; escaping `\n` inside those
  strings has broken pages many times (see the many "Fix SyntaxError" commits) - check the
  rendered JS after editing.

## Keeping this current (every session)

1. Before starting: read this file, `worklog/README.md` and the app's worklog file.
2. After a change: add a line to that app's **Work log** section (date, what and why, PR,
   anything left undone) and update **Where it stands** / **Open threads** if they changed.
   Update the status board in `worklog/README.md` if an app's status changed.
3. Regenerate the git history sections: `git fetch --unshallow` (if shallow), then
   `python tools/build_worklog.py`.
