# Pumps as its own Railway service

Pumps (`pumps.py`) can run inside the Office App (how it has always run) or as
its own Railway service (`pumps_server.py`). On its own, a Pumps update only
redeploys Pumps, and PO, Community Maintenance, Receivables and the rest of the
Office App keep running.

The switch is one variable on the Office App, `PUMPS_URL`. Without it,
everything works as before.

## How the pieces fit

| | Office App (`app.py`) | Pumps service (`pumps_server.py`) |
|---|---|---|
| Login | People log in here, as always | No password of its own. The Office App's `/pumps` sends people here with a 2-minute signed ticket (`pumps_link.py`) |
| Who may open Pumps | Decided here (`pumps_allowed`, same roles as before) | Checks again from the ticket |
| Data | Keeps its old copy of the `pump_*` tables and `pump_files/`, untouched | Its own volume: `/data/pumps.db` and `/data/pump_files/` |
| Jobber | Receivables asks the Pumps service for the token over the private network | Owns the Jobber connection |
| Mailbox | Scans for PO / vendor invoices | Scans for pump work (its own scan log) |

## Pumps service settings

Railway service **Pumps**: repo `SimonSEI/PO-Request-app`, branch `main`,
config file `/railway.pumps.json` (start command, health check and watch
patterns are in that file), volume mounted at `/data`, Railway-generated domain.

Variables:

| Variable | Value |
|---|---|
| `SECRET_KEY` | **The same value as the Office App's.** Pumps' saved Jobber sign-in is encrypted with it. |
| `PUMPS_SHARED_SECRET` | A new random string (32+ characters). The same value goes on the Office App. |
| `DATA_DIR` | `/data` |
| `PORT` | `8080` |
| `WEBSITE_URL` | This service's own address, e.g. `https://pumps-production-xxxx.up.railway.app`. Report links that Jobber fetches use it. |
| `OFFICE_APP_URL` | `https://web-production-01609.up.railway.app` |
| `OFFICE_INTERNAL_URL` | `http://web.railway.internal:<Office App port>` |
| `PUMPS_AUTO_SCAN` | `false` until the switch-over, so it doesn't scan the mailbox or send digests early |
| Copied from the Office App | `ANTHROPIC_API_KEY`, `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `PO_EMAIL_ADDRESS`, `PO_EMAIL_PASSWORD`, `PO_EMAIL_PROVIDER`, `PUMPS_JOBBER_CLIENT_ID`, `PUMPS_JOBBER_CLIENT_SECRET`, and any other `PUMPS_*` or `CHRISTIAN_EMAIL` it has |

**Jobber developer app:** add `https://<pumps address>/pumps/jobber/callback`
as a redirect URI. You only need this to click *Connect Jobber* again; the
existing connection moves over with the data.

## Switch-over (a quiet time, about 10 minutes)

1. **Back up.** Office App → Backup database.
2. **Office App variables:** set `PUMPS_URL` (the Pumps address),
   `PUMPS_INTERNAL_URL` (`http://<pumps private name>.railway.internal:8080`)
   and `PUMPS_SHARED_SECRET`. The Office App redeploys. From then on Pumps no
   longer runs there, and the dashboard tile opens the Pumps service.
3. **Pumps variables:** set `PUMPS_IMPORT_FROM_OFFICE=true` and remove
   `PUMPS_AUTO_SCAN`. Pumps redeploys and, before it starts, copies the
   Office App's Pumps data. It checks every table's row count and every file's
   size, and refuses to start if anything doesn't match. The deploy log shows
   `✓ Pumps import: N rows in N tables, N files - all checked`.
4. **Check:** open Pumps from the dashboard, look at a few cases and files,
   and check Receivables still shows Jobber as connected.
5. **Office App watch patterns:** stop Pumps-only files redeploying it by
   adding `!/pumps.py`, `!/pumps_page.py`, `!/pump_reports.py`,
   `!/pumps_server.py`, `!/pumps_assets/**` and `!/railway.pumps.json`.

The copy runs only once (a marker file on the Pumps volume), so later deploys
and restarts don't touch the data. Anything already on the Pumps volume is
renamed to `*.before-import-<time>`, never overwritten.

## Going back

Remove `PUMPS_URL` from the Office App. Pumps runs there again, from the copy
it kept at the moment of the switch. Anything entered in the Pumps service
after the switch is not in that copy and would have to be re-entered.
