# Work log - every app

One file per app. Each has a hand-written top (status, what it is, where it stands, open
threads, a dated work log) and a **History** section generated from git by
`python tools/build_worklog.py`. Start with `../AI_CONTEXT.md` for the big picture.

## Status board (2026-10-13)

| App | Status | Commits | First | Last |
|---|---|---:|---|---|
| [Pumps](pumps.md) | **Live, most active app** (daily work since Oct 2026) | 97 | 2026-06-10 | 2026-10-13 |
| [Receivables](receivables.md) | **Live, new** (started 2026-10-08) | 6 | 2026-10-08 | 2026-10-13 |
| [Community Maintenance](community.md) | **Live** | 210 | 2026-02-25 | 2026-10-09 |
| [PO Requests](po.md) | **Live** (the original app; quiet since 2026-06) | 239 | 2026-01-19 | 2026-06-24 |
| [Snowbirds](snowbirds.md) | **Live** (separate R/Shiny services on Railway) | 56 | 2026-09-15 | 2026-09-23 |
| [Installation](installation.md) | **Partly live**: open to install technicians; shown to office under "Features Coming Soon" | 39 | 2026-03-26 | 2026-06-10 |
| [Cash Flow & AR](cashflow.md) | **Switched off** unless `CASHFLOW_ENABLED=true` | 5 | 2026-09-23 | 2026-09-24 |
| [Time-Off Log (parked)](timeoff.md) | **Parked** - `TIMEOFF_ENABLED = False` in `app.py`; tile inoperable in "Features Coming Soon" | 4 | 2026-10-01 | 2026-10-05 |
| [Work Orders (archived)](workorders.md) | **Archived** 2026-10; tile shows disabled in "Features Coming Soon" | 13 | 2026-06-10 | 2026-10-12 |
| [Platform (login, admin, deploy, security)](platform.md) | Live | 52 | 2026-01-20 | 2026-10-01 |

Commit counts and dates are from the generated History and change when it is rebuilt; the
status column is hand-written - update it when an app goes live, is switched off or archived.

## In flight

- **Pumps** - daily changes; see "Open threads" in [pumps.md](pumps.md).
- **Receivables** - new (2026-10-08), being tuned against real A/R uploads.
- Open PRs that look stale: [#461](https://github.com/SimonSEI/PO-Request-app/pull/461) (Work Orders map pins, June),
  [#108](https://github.com/SimonSEI/PO-Request-app/pull/108) and [#103](https://github.com/SimonSEI/PO-Request-app/pull/103) (PO tech dashboard, March).

## How commits are sorted into apps

By the files a commit changes when they belong to one app's module (`pumps.py`,
`receivables.py`, `snowbirds/`, ...); otherwise by its subject line; otherwise by which app's
code its `app.py` diff touches most. It is a heuristic: a commit can land under the wrong app,
mostly early `app.py` commits between PO Requests and Community Maintenance. Rules are in
`APPS` at the top of `tools/build_worklog.py`.
