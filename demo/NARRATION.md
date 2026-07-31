# The Office App — demo reel narration script

Companion to `demo/office-app-demo.html`. Read straight through for a voiceover;
timecodes are chapter starts at the reel's built-in pacing (6:11 total).

## Watching it

- **In a browser** — open `demo/office-app-demo.html`. Play/pause with Space,
  skip chapters with the arrow keys, click the timeline to scrub.
- **Full screen, no chrome** — add `#video` to the URL. The reel fills the
  window as one frame with the narration burned in as a lower third. Good for
  playing on a TV or in a meeting.
- **As a video file** — `demo/office-app-demo.mp4`, 1920×1080, 30fps, silent
  with the narration on screen.

## Re-rendering the MP4

The video is not committed (it is in `.gitignore`); regenerate it whenever the
reel changes:

```
pip install playwright imageio-ffmpeg
python3 demo/render-video.py --out demo/office-app-demo.mp4
```

The reel exposes `window.__reel.frame(seconds)` in `#render` mode, which paints
one exact frame with nothing left to the wall clock. The script walks the
timeline at a fixed frame rate and pipes frames straight into ffmpeg, so the
output is frame-accurate rather than a screen recording. Flags: `--fps`,
`--scale` (device pixel ratio, 1.5 → 1080p, 3 → 4K), `--crf`, `--quality`.

## Adding a voiceover

The MP4 has no audio track. To narrate it, record this script against the
timecodes below and mux the result in:

```
ffmpeg -i office-app-demo.mp4 -i voiceover.wav \
       -c:v copy -c:a aac -shortest office-app-demo-narrated.mp4
```

The reel's **Voiceover** button (browser mode only) reads the script aloud with
the browser's own speech synthesis and holds each scene until the line
finishes — useful for timing a read, but a human voice will sound better.

---

## 0:00 — Cold open: The Office App

This is the Office App — the system Stahlman-England Irrigation runs its whole
operation on.

Six applications behind one login: purchase orders, invoices, install jobs,
community maintenance routes, homeowner work orders, and pumps.

Two hundred and sixteen routes, forty-five tables, and three places where an AI
agent does work a person used to do.

## 0:24 — Roles: Five roles, one door

It starts with who you are. Sign in once, and the app shows you only the work
that belongs to you.

Technicians raise POs and log field work. The office matches invoices and costs
jobs. Admins manage accounts. Property managers see only their own communities.
Homeowners get a public portal of their own.

And every screen speaks English or Spanish — the crews toggle it themselves, and
it sticks to their account.

## 0:46 — PO Requests: Purchase orders

Start with the thing the field does most: raising a purchase order. A tech picks
the job, types what they're buying, and submits.

If they misspell the job name, the app fuzzy-matches it back to the real one
rather than rejecting it. It assigns the PO number itself — an S or I prefix for
service or install, with the job code appended. Status: awaiting invoice.

Closed jobs are refused outright, so a PO can't be raised against work that's
finished. And every action is written to an audit log.

## 1:11 — Invoices: The inbox worker

Then the PO sits open and waits — because the invoice arrives on its own.

Every hour, the app checks the PO inbox over Microsoft Graph, reads each PDF,
runs OCR on anything scanned, and asks Claude to pull out the vendor and invoice
number.

Then it matches: exact PO number first, fuzzy second, and Claude last —
committing only above sixty percent confidence.

Here's a real morning. Two invoices matched themselves. One was uncertain, so it
became a notification instead of a guess.

That's the rule throughout: when it isn't sure, it hands the decision back. The
office resolves it in two clicks, any match can be undone, token spend is
logged, and the whole AI layer has an off switch.

## 1:48 — Job Costing

All of that feeds job costing. Import the proposal — materials, labor, travel,
subs, rental, permits, days allotted — and every PO and invoice after it is
scored against that budget.

Solid is what's been invoiced. Faded is committed but not yet billed. Amber is
over budget.

Which means the office sees a job going the wrong way while there's still time
to do something about it.

## 2:11 — Installation

The installation side carries a whole install job front to back.

Versioned proposals with a shared rate card. Site plans where one revision is
marked current. Crew scheduling by the week.

Daily logs with photos. Expenses with receipts. Change orders the client
approves from an emailed link, with no account. And RFIs tracked against the
job.

Vendor invoices get parsed out of spreadsheets, checked against Jobber by
proposal number — and when Jobber marks one paid, the email goes out
automatically.

## 2:38 — Community maintenance

Community maintenance replaced a clipboard. A tech picks a community and a date,
and gets a sheet built from that community's own clocks and addresses — imported
from the spreadsheets the office already had.

Counts per zone: nozzles, pop-ups, rotors, solenoids. It saves as a draft on the
truck, takes photos, and submits at the end of the day.

The office reviews it, prices it from that community's rate sheet, and exports
the month to Excel. Deleted submissions come back, and a bad import undoes in
one action.

## 3:03 — Work orders

Work orders open the system up to the people the company actually works for. A
homeowner logs in, describes the problem, and drops a pin on a satellite view of
their own street.

Their property manager sees every request across the communities they oversee —
status, pins, technician notes. The tech in the field adds notes and closes it
out, or flags it as needing a quote.

That last flag is the interesting one. It's the seam where OpenClaw picks the
job up.

## 3:25 — Pumps

Pumps is the smallest app and the most automated. The same inbox scanner runs a
second pass, filtering for pump equipment — transducers, VFDs, wet wells, flow
meters.

Matches land in a monthly tracker tab that mirrors the old spreadsheet, and an
agent drafts the invoice in Jobber, matches the client, and writes the invoice
number back.

If Jobber refuses a draft, the row is kept and marked needs review. A draft is
never lost.

And there's a live authenticated endpoint where OpenClaw can file a pump request
itself, with nobody in the loop at all.

## 3:55 — Under the hood

Underneath, it's deliberately boring. Flask and SQLite on Railway. Every route
checks your role. CSRF tokens on every form. Login rate limited. A full audit
log, and one-click database backups.

Because it has to run on a phone, in the sun, on a job site, on whatever signal
the truck has.

## 4:11 — OpenClaw: three seams

Which brings us to OpenClaw, and what it's actually doing right now.

There are three seams. One is running today: drafting quotes in Jobber. One is a
live endpoint: pump intake. And one is fully wired but switched off — work-order
quote drafting, which is a single environment flag away from being on.

The plumbing is authenticated in both directions. The app can hand work out, and
OpenClaw can post its result back against the same work order.

## 4:35 — The quoting loop

The quoting work is a loop it runs every day, in six steps.

First, discovery: it pulls every quote sitting in draft status in Jobber.
Second, triage: it reads the internal notes — materials and a scope of work from
a technician means it processes the quote; nothing there and it skips it,
untouched.

Third, it titles the quote: "ESTIMATE - IRRIGATION" becomes "Bermad Solenoid
Installation".

Fourth, it builds the line items — materials with quantities, crew labor
converted to the right unit, and a scope paragraph for the client — batched to
Jobber's catalog matcher, which links each item to Products and Services and
pulls pricing.

Fifth, it cleans up: it drops the placeholder line and leaves an internal note
recording exactly what it changed. And sixth, it posts a summary in the
quotes-review channel so Beatriz knows what's ready to price.

## 5:08 — Guardrails

What matters just as much is where it stops.

It doesn't set final prices — that stays with Beatriz and the office. It doesn't
send anything to a client. It won't touch a quote with no technician notes. And
it never invents materials: every line comes off the tech's list.

It does the assembly. A person still decides what the work is worth.

## 5:31 — From today: Quote #8899

Here's one from today. Quote 8899 came in as "ESTIMATE - IRRIGATION", with a
placeholder line item and a note from Jimmie about troubleshooting Zone 6 at
Clock 2.

It came out titled, with a scope description written from those notes, the
placeholder removed, and flagged for the office to price as time and material.

Jimmie wrote what he found. Nobody retyped anything.

## 5:53 — Where things stand

So — where things stand. POs, invoices, job costing, community billing and
installation are in daily use. OpenClaw's Jobber quoting is running now. Pumps
and work orders are in preview, and work-order quote drafting is one flag from
live.

Everything the field does now leaves a record. And everything the office repeats
is being handed, one seam at a time, to something that doesn't mind repeating
it.

---

## Source notes

Everything stated in the reel is drawn from `app.py` in this repo:

| Claim | Where it comes from |
| --- | --- |
| Six apps, role-based dashboard | `DASHBOARD_TEMPLATE` app cards, gated on `role` / `tech_type` |
| 216 routes | `@app.route` count in `app.py` |
| EN/ES toggle | `/set_user_language`, `T={en:…,es:…}` in the dashboard template |
| PO prefix + fuzzy job match | `submit_request`, `get_next_po_number_with_prefix`, `fuzzy_match_score` (≥0.70) |
| Hourly inbox scan | `scheduler.add_job(auto_check_po_emails, 'interval', hours=1)` |
| Graph API with IMAP fallback | `_fetch_emails_for_vi_scan`, `PO_EMAIL_MONITORING_ENABLED` |
| Claude extraction + 3-tier match | `claude-haiku-4-5` extraction; exact → fuzzy → `match_invoice_with_claude` at ≥0.6 |
| Token/cost logging + off switch | `claude_api_log`, `is_claude_matching_enabled`, `/settings/toggle_claude` |
| Proposal budget import | `job_proposals` table, `/job_costing/import_proposal` |
| Installation modules | `install_proposals`, `install_rate_card`, `installation_site_plans`, `installation_crews`, `installation_daily_logs`, `installation_expenses`, `installation_change_orders`, `installation_rfis` |
| Client change-order approval link | `/installation/co/approve/<token>` |
| Jobber paid-invoice email | `get_jobber_invoice_status`, paid-notification email |
| Community sheet + Excel export | `community_billing_*` routes, `/community_billing_export_excel`, `/undo_import` |
| Work orders + map pin | `wo_work_orders` (`pin_lat`/`pin_lng`), `wo_pm_communities`, `/workorders/portal` |
| Pump keyword filter + monthly tab | `PUMP_KEYWORDS`, `pump_month_tab`, `scan_emails_for_pump_invoices` |
| Pump agent → Jobber | `process_pump_agent_request`, `create_jobber_invoice_draft` |
| OpenClaw pump webhook | `POST /api/openclaw/pumps`, `hmac.compare_digest` on `OPENCLAW_API_KEY` |
| Work-order quote drafting, off by default | `draft_workorder_quote_via_openclaw`, `WORKORDERS_OPENCLAW_QUOTES` (default `false`) |
| OpenClaw result callback | `POST /api/openclaw/workorders/quote` |
| Security + ops | `CSRFProtect`, `limiter.limit("10 per minute")` on login, `activity_log`, `/backup_database`, `railway.json` gunicorn config |

The OpenClaw quoting loop (chapters 11–13) is the workflow as described by the
agent itself — it runs against Jobber outside this codebase, so there is no
source file to point at.
