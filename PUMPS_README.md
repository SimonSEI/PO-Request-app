# Pumps

The Pumps tile in The Office App tracks every pump, diver, filter and SCADA job for a client. It follows each one from the first request to the invoice so nothing gets lost between the request, Wettech, Wettech's bill and our invoice.

- **Who can open it:** office logins, or only the usernames listed in `PUMPS_USERS`. Technicians and property managers never can.
- **Code:** `pumps.py` (logic and API), `pumps_page.py` (the page), `pump_reports.py` (report rebranding), `pumps_assets/report_letterhead.docx` (our letterhead). It is hooked into `app.py` with `init_pumps(...)` and uses the same SQLite database, in tables starting `pump_`.
- **OpenClaw:** see `PUMPS_OPENCLAW.md` for its instructions and the API.

## What it does

| | |
|---|---|
| **Items** | One row per client need (the old monthly pump sheet, one row per PO). Each item has a checklist: quote from Wettech → quote sent to client → client approved → scheduled with Wettech → work done → Wettech's bill → bill checked against the quote → draft invoice in Jobber → report logged in Jobber → invoice sent and closed. Steps that don't apply start crossed out. For example, maintenance visits have no quote. |
| **PO@ mailbox** | Every 30 minutes it reads new mail for Wettech quotes, bills and Word pump reports. Each one is filed against its item by PO number, Wettech W/O number, the quote number or the client's name. If none match, a new item is opened. Mail from anyone other than a known pump vendor is only picked up when it is clearly about pump work, and it waits in the Inbox for someone to confirm it. |
| **When Claude is down** | If Claude can't read documents (for example the Anthropic account is out of credits), the page header says so. New quotes and bills are still downloaded, read roughly, and wait in the Inbox marked *Read without Claude*. Once Claude works again, each mailbox scan reads them again and files the ones that now read cleanly. *Read again with Claude* on a document does the same straight away. Documents already on an item are left alone. |
| **Bill check** | A bill that differs from its quote by more than $0.50, or arrives with no quote, raises an **issue**. Issues stay at the top of Today until someone resolves them and writes down how. |
| **Client quotes (automatic)** | When a Wettech quote is read cleanly and filed, the app drafts our quote to the client in Jobber on its own, the way the office writes them (modelled on Jobber quote 9136): Wettech's price plus `PUMPS_QUOTE_MARKUP_PCT` (default 30%), no Wettech name or sales tax line, a single-price quote as one **Service Proposal Amount** line carrying Wettech's description of the work, titled "Proposal to …". A price that already includes Wettech's sales tax stays not taxable. The client and property come from the item, a **site name** (below), or a Jobber search that also looks at property addresses and allows typos ("The Carlise" finds the Carlisle properties on the Greenscapes account). Wettech's quote is saved as a note on our quote (attached, or linked if Jobber won't take the file). It is created as a **draft** and nothing is sent: the office reviews it and sends it from Jobber. If the client or property isn't clear, nothing is created and the quote waits on Today with what to choose; *Draft quote in Jobber* opens with the app's best match filled in. Once it's sent, *Quote sent to client* ticks itself at the next sync, and *Client approved* once the client approves it. Set `PUMPS_AUTO_DRAFT_QUOTES=false` to only draft on a click. OpenClaw cannot draft quotes. |
| **Site names** | Some accounts have their own names for sites on Wettech's paperwork: "Carlisle" is on the Greenscapes account, and its "back station" is the Pump #1 exit. These are kept in the Jobber tab under *Site names* (the Carlisle ones are there already) and are matched against the quote's RE: line, file name, email subject and site, typos allowed. Add one by ticking *Remember* in the Draft quote dialog. |
| **Paying Wettech** | Each item shows whether Wettech's bill is paid. Once the client **pays** our Jobber invoice (seen at the next sync, even on a closed item), the bill goes to the top of Today as *Pay Wettech - the client has paid* until someone clicks *Mark paid* and gives the date. The app does not pay anyone, and OpenClaw cannot mark a bill paid. |
| **Draft invoices** | From a bill, *Draft invoice in Jobber* copies the bill's line items into a new Jobber invoice **as a draft**. It leaves off Wettech's sales tax (Jobber adds the client's), plus any `PUMPS_MARKUP_PCT`. The app cannot send invoices or quotes: the only Jobber changes it is allowed to make are creating draft quotes, creating draft invoices and adding notes (`ALLOWED_MUTATIONS` in `pumps.py`), and anything else is refused before it reaches Jobber. If Jobber ever reports the new invoice as anything other than a draft, an issue is raised. |
| **Reports** | Wettech's Word reports are rebranded automatically. Our letterhead goes on top, Wettech's header is removed, their name becomes ours, their phone, email and licence number are removed, and the technician's signature row and name are removed (prose mentions become "our technician"). "Stahlman-" is also taken off the customer name. *Log in Jobber* then adds the report as a note on the pump's job (or the client). |
| **SCADA** | Built from the SCADA jobs, quotes and invoices in Jobber: each client's last renewal, and the next due a year later. Overdue and due-within-60-days rows go on Today. *Start renewal* opens an item: quote the client, then order it from Wettech. |
| **Jobber tab** | Open pump, diver, filter and SCADA requests, quotes, jobs and draft invoices, synced every 6 hours. *Track* turns one into an item, and anything with a PO number in its title links itself. Recurring pump maintenance jobs are listed as service contracts. |

The preview's old sheet rows (`pump_invoices`) were copied into items the first time the app started. The old table is left untouched.

## Setup (Railway → Office App → Variables)

| Variable | Needed for | What it does |
|---|---|---|
| `PUMPS_JOBBER_CLIENT_ID`, `PUMPS_JOBBER_CLIENT_SECRET` | Jobber | Keys from a Jobber app made for Pumps (see below). |
| `PUMPS_USE_CLAUDE` | optional | Off by default: Pumps reads Wettech's quotes (Word letters), invoices (PDF) and reports with its own reader, needs no Anthropic credits, and files and drafts on its own whatever it reads cleanly (a known vendor, an amount, and a client, PO or W/O). Anything else waits in the Inbox. `true` = use Claude (with the PO app's `ANTHROPIC_API_KEY`) for other vendors' layouts. |
| `OPENCLAW_API_KEY` | OpenClaw | Already used by Work Orders. OpenClaw sends it as `Authorization: Bearer <key>`. |
| `PUMPS_USERS` | optional | e.g. `simon,beatriz`. Only these usernames can open Pumps. |
| `PUMPS_MARKUP_PCT` | optional | Added to Wettech's bill prices on drafted invoices when there is no client quote to copy (default `0`). When the bill matches Wettech's quote and the item has our Jobber quote, the invoice copies that quote's lines instead. |
| `PUMPS_QUOTE_MARKUP_PCT` | optional | Added to Wettech's price on client quotes (default `30`). |
| `PUMPS_AUTO_DRAFT_QUOTES` | optional | `false` = client quotes are only drafted when someone clicks *Draft quote* (default `true`). |
| `PUMPS_SCAN_SINCE` | optional | The first mailbox scan only reads mail received on or after this date (`YYYY-MM-DD`). The default is 60 days back. |
| `PUMPS_COMPANY_PHONE`, `PUMPS_COMPANY_EMAIL` | optional | Put in place of Wettech's on rebranded reports. Unset = theirs are simply removed. |
| `PUMPS_WEBHOOK_URL` | optional | Receives a POST whenever an issue is raised (e.g. bill over quote), signed with `X-Pumps-Signature` (HMAC-SHA256 of the body using `OPENCLAW_API_KEY`). |
| `PUMPS_VENDORS_JSON` | optional | More pump subs besides Wettech: `[{"key":"acme","display":"Acme Pumps","names":["Acme Pump Co"],"emails":["acmepumps.com"],"phones":[],"other":[],"sender_match":["acmepumps"]}]`. |

### Connecting Jobber

Pumps needs its own Jobber app because, unlike Cash Flow (read-only), it writes draft quotes, draft invoices and notes.

1. At developer.getjobber.com, create an app called "Office App - Pumps".
2. Scopes: **read** Requests. **Read and write** Clients and Jobs (to add notes), Quotes and Invoices (to create drafts). Write scopes are broader than Pumps needs. What keeps it to drafts and notes is the app's allow-list, which refuses every other Jobber change, including anything that sends or marks as sent. If the app was made before quotes were added, turn on write access to Quotes, then click **Connect Jobber** again so the new access takes effect.
3. Callback URL: `<WEBSITE_URL>/pumps/jobber/callback`. Set `PUMPS_JOBBER_CALLBACK_URL` if the app is reached at a different address.
4. Put the app's Client ID and Secret in Railway as `PUMPS_JOBBER_CLIENT_ID` and `PUMPS_JOBBER_CLIENT_SECRET`, and let it redeploy.
5. On the Pumps page, click **Connect Jobber** and allow access. The first sync of pump work starts on its own and takes a few minutes.

The sign-in is stored encrypted (key: `PUMPS_TOKEN_KEY`, or derived from `SECRET_KEY` when unset) and refreshes itself.

### PDFs of reports

Rebranded reports are Word files. *PDF* works only if LibreOffice is installed on the server. On Railway that means adding `libreoffice-writer` to the build packages (`NIXPACKS_APT_PKGS=libreoffice-writer`), which makes the image much larger. Otherwise open the Word file and save it as PDF.

## Not yet confirmed against the live Jobber account

These Jobber calls were written from Jobber's API conventions and two public projects that use them. They have not been run against your Jobber account yet:

- **Report attachments.** The note is first sent with the report attached by link. If Jobber rejects that, the note is saved again without the attachment and with a link to the report in this app. The item's history says which happened.
- **Creating quotes** (`quoteCreate`). Written from Jobber's documented fields (client, property, title, line items). If Jobber rejects the line items' tax or Products & Services settings, the quote is tried once more without them, and any other refusal shows as the error in the dialog.
- **Searching Jobber by keyword** (`searchTerm`). If a search is refused, the Jobber tab shows the error after a sync instead of failing silently.

## Tests

```
pip install -r requirements.txt
python -m unittest tests.test_pumps -v
```

The tests use a throwaway database, made-up documents, and a fake Jobber that also re-checks that only draft-quote, draft-invoice and note mutations are ever sent.
