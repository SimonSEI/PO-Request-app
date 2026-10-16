# Time-Off Log

> **Switched off for now.** The tile sits in "Features Coming Soon" on the dashboard and can't
> be opened; `/timeoff` and the `/api/time-off` endpoints return 404. To turn it back on, set
> `TIMEOFF_ENABLED = True` in `app.py` and move the tile back into the main grid. Existing
> records in `timeoff_requests` and `timeoff_audit` are untouched.

A new app tile in The Office App for technician time-off requests and sick call-outs.
Beatriz approves or denies requests; OpenClaw (the AI scheduling assistant) adds them and
reads them through an API.

- **Who can open it:** office logins, or exactly the usernames in `TIMEOFF_USERS`.
  Technicians and property managers never can, whatever is set. They don't see the tile,
  `/timeoff` sends them to the login page, and the API returns 401.
- **Privacy:** a request stores who, which dates and the decision, never why. If a payload
  includes `reason`, `notes`, `details`, `medical` or a similar field, that field is dropped
  before saving and listed back in `ignored_fields`.
- **Time zone:** all dates and times are America/New_York.

Code: `timeoff.py`, hooked into `app.py` with `init_timeoff(app, csrf, DB_PATH)`. It uses the
same SQLite database, in the `timeoff_requests` and `timeoff_audit` tables.

## Setup (Railway → service → Variables)

| Variable | Required | What it does |
|---|---|---|
| `TIMEOFF_API_TOKEN` | yes, for OpenClaw | The token OpenClaw sends as `Authorization: Bearer <token>`. While it is unset, the API refuses every token call. |
| `OPENCLAW_WEBHOOK_URL` | yes, for app decisions | When Beatriz approves or denies in the app, the updated record is POSTed here. |
| `OPENCLAW_WEBHOOK_SECRET` | optional | Sent with each webhook as `Authorization: Bearer <secret>` and used to sign it (see below). |
| `TIMEOFF_USERS` | optional | e.g. `simon,beatriz`. Only these usernames can open the app. Set it if Beatriz's login is not an office account. |

1. Generate a token: `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
2. Add it as `TIMEOFF_API_TOKEN` in Railway and give the same value to OpenClaw. Keep it out
   of the code and out of Slack.
3. Add `OPENCLAW_WEBHOOK_URL` (plus `OPENCLAW_WEBHOOK_SECRET` if OpenClaw checks one).
4. Redeploy. Until both are set, the Time-Off page shows a yellow banner naming whichever is missing.

To rotate the token, change the variable, redeploy, and update OpenClaw.

## API (for OpenClaw)

Every call needs `Authorization: Bearer $TIMEOFF_API_TOKEN`. Use JSON bodies.
Dates are written `YYYY-MM-DD` and times `HH:MM` (24-hour; `8:00 AM` is also accepted).

```
POST  /api/time-off                   create a request
PATCH /api/time-off/:id               decide, cancel, record a reminder, confirm
GET   /api/time-off?status=&tech=&from=&to=&type=   list (status may be comma-separated)
GET   /api/time-off/:id               one request, with its full status history
GET   /api/time-off/whos-off?date=YYYY-MM-DD        who's off that day (default: today)
GET   /api/time-off/summary?tech=&year=             days taken per tech (default: this year)
```

**Create:**
```json
{"tech_name": "Ramon Diaz", "jobber_user_id": "…", "slack_user_id": "U123",
 "type": "TIME_OFF", "start_date": "2026-10-09", "end_date": "2026-10-12",
 "start_time": null, "end_time": null, "requested_via": "Slack",
 "requested_at": "2026-10-01T09:14:00-04:00", "affected_visits_count": 6,
 "reported_by": null}
```
- `type` is `TIME_OFF` (starts as `PENDING`) or `CALL_OUT` (starts as `APPROVED`, so it only needs to be seen).
- If `end_date` is left out, the request covers one day. `days_count` counts weekdays only.
- If `reported_by` is set (someone reporting time off for another tech), the record is marked
  `unconfirmed: true` and the app shows an "Unconfirmed – reported by X" badge. To confirm it later,
  send `PATCH {"unconfirmed": false}`.
- A request is rejected if a date isn't real, if `end_date` is before `start_date`, or if the
  same tech already has a **pending** request overlapping those dates. Same tech means the same
  name, Jobber id or Slack id. That last case returns 409 with `existing_id`.

**Update:**
```json
{"status": "APPROVED", "decided_by": "Beatriz"}   // APPROVED | DENIED | CANCELLED
{"reminder_sent_at": "now"}                       // or an ISO timestamp
```
`decided_by` is required to approve or deny. A cancelled request can't change again.
Each status change is written to the audit trail: who, when, the old status, the new status,
and whether it came from the app or the API. Records include `reminder_due: true` once a
request has waited one business day without a decision or a reminder.

`tech=` matches a full name, a first or last name, a Jobber id or a Slack id. So
"How many days has Ramon taken this year?" is `GET /api/time-off/summary?tech=Ramon`.
That returns `days_taken`, which counts weekdays up to today: approved time off plus call-outs.
It also returns `days_booked` for the whole year and the `upcoming` approved time off.
"Who's off this month?" is `GET /api/time-off?status=APPROVED&from=2026-10-01&to=2026-10-31`.

## Webhook (app → OpenClaw)

When someone approves or denies a request in the app, the app POSTs this to `OPENCLAW_WEBHOOK_URL`,
so OpenClaw can rename the Jobber calendar block and tell the tech:

```json
{"event": "time_off.status_changed", "from_status": "PENDING", "to_status": "APPROVED",
 "changed_by": "Beatriz", "changed_at": "2026-10-01T10:02:11-04:00", "source": "app",
 "record": { …the full updated request… }}
```
- If `OPENCLAW_WEBHOOK_SECRET` is set, the request also carries `Authorization: Bearer <secret>`
  and `X-TimeOff-Signature: sha256=<HMAC-SHA256 of the raw body>`.
- A failed delivery is retried twice. If it still fails, the row shows "OpenClaw not notified ↻",
  and clicking that badge resends it.
- Changes OpenClaw makes itself through `PATCH` (for example, Beatriz replying in Slack) are
  **not** sent back to it, since OpenClaw already knows.
