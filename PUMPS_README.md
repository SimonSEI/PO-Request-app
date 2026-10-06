# Pumps

The Pumps tile in The Office App tracks every pump, diver, filter and SCADA job for a client. It follows each one from the first request to the invoice so nothing gets lost between the request, Wettech, Wettech's bill and our invoice.

- **Who can open it:** office logins, or only the usernames listed in `PUMPS_USERS`. Technicians and property managers never can.
- **Code:** `pumps.py` (logic and API), `pumps_page.py` (the page), `pump_reports.py` (report rebranding), `pumps_assets/report_letterhead.docx` (our letterhead). It is hooked into `app.py` with `init_pumps(...)` and uses the same SQLite database, in tables starting `pump_`.
- **OpenClaw:** switched off; `PUMPS_OPENCLAW.md` describes the API if it's turned back on.

## What it does

The office's flow (decided October 2026): **request → vendor quote → our Jobber quote → client approves → vendor does the work → vendor bill → our invoice at the quoted price → client pays → pay the vendor**, for Wettech (pumps, Tommy, tomm@wettec.biz) and Gulfshore (lakes and divers, Jordan, Gulfshoreyachts@gmail.com), plus SCADA renewals.

The page has five tabs: **Today** (to-dos and everything waiting on someone), **Jobs** (one list of every job with where it is and links to Jobber), **SCADA**, **Accounts** (pump, lake and SCADA clients in one list) and **Reports**.

| | |
|---|---|
| **Service-call emails** | A plain email to PO@ (no attachment, from a client - not a vendor) that mentions a pump, lake, fountain, filter or SCADA **and** names one of our accounts opens a job and adds a "Service call - &lt;subject&gt;" visit to that client's ongoing (recurring) maintenance job in Jobber. If Jobber's API won't take the visit, a to-do says to add it. Emails from the last 14 days are read (`PUMPS_SERVICE_CALL_DAYS`). |
| **Vendor quotes → our quote** | Wettech and Gulfshore quotes arrive in PO@ by themselves. Each one read cleanly is filed onto its job and our quote is drafted in Jobber on the client's account (not inside the maintenance job), the way the office writes them (Jobber quote 9136): always **one Service Proposal Amount line**: the vendor's total before tax **plus 30%** (`PUMPS_QUOTE_MARKUP_PCT`) with their descriptions of the work, titled "Proposal to …", the vendor's quote saved as a note on it. **SCADA is not marked up**: a SCADA renewal quote uses the client's price from the SCADA tab. Drafts only - the office sends them from Jobber. If the client or property isn't clear it waits on Today. *Site names* (Accounts tab) teach it the office's names ("Carlisle" = Greenscapes, Spanish Wells = The Lake Club). |
| **Client approves** | When the next Jobber sync sees our quote approved, the vendor's quote is stamped **APPROVED - Simon Weardon** with the date (`PUMPS_APPROVER`), kept on the job and added to the Jobber quote as a note, and the quote is made a job where Jobber's API allows it (otherwise a to-do: "Convert Jobber quote #… to a job"). A to-do - "Send the approved quote back to Tommy (tomm@wettec.biz)" or Jordan for Gulfshore - has the stamped PDF and a ready email. *Approved* on a job does the same by hand. |
| **Vendor bill → our invoice** | When the vendor's bill arrives for a job we quoted, our invoice is drafted in Jobber on that job **at the price the client approved** (our quote's lines). If the bill doesn't match the vendor's quote, a to-do says to check with Tommy (or Jordan) - the invoice is still drafted at the quoted price. A bill with no quote raises an alert; *Bill it +30%* clears it and drafts one Service Proposal Amount line at the bill before tax plus 30%. Maintenance is billed by the recurring Jobber jobs. |
| **Paying the vendor** | Once the client **pays** our Jobber invoice (seen at the next sync), the vendor's bill goes to the top of Today as *Pay the vendor - the client has paid* until someone clicks *Mark paid*. The app pays no one. |
| **Service reports** | Wettech's Word service reports are rebranded on every page (our letterhead, no Wettech details, no technician, not "Stahlman England" as the customer), a PDF made (LibreOffice), kept on the **Reports** tab by year and month, and put on the site's pump job in Jobber as "&lt;Month&gt; Pump Maintenance" with the PDF. |
| **SCADA** | The office's SCADA sheet, brought up to date from Jobber: each year holds our invoice #, and every Jobber sync reads the last 14 months of invoices and writes in new SCADA renewal invoices itself (matched by client or *Name in Jobber* - Cross Creek is billed to Medallion Home). **30 days** before a renewal (`PUMPS_SCADA_DUE_SOON_DAYS`) the app drafts the client's quote in Jobber at their price and adds a to-do to send it. Complimentary ones (Autumn Woods - we pay; Reserve at Estero - in their monthly) are a reminder only. Old Collier and Camas Willows are off SCADA. |
| **Accounts** | One row per client: Wettech pump maintenance (schedule, Wettech's price, our bill), Gulfshore lake/diver work (diver or not, schedule, Gulfshore's price, our bill) and SCADA. Also the monthly diver email settings and the site names. |
| **Jordan's list** | On the 1st, the month's diver list is emailed to Jordan from PO@ (cc Andrea) with the Word list attached. If Microsoft 365 can't send, it stays a to-do with the email ready to copy. |
| **Daily email** | Every weekday at 8am (`PUMPS_DIGEST_HOUR`) a summary goes to simon@stahlman-england.com (`PUMPS_DIGEST_TO`): to-dos, vendors to pay, SCADA due, quotes waiting, jobs waiting on the vendor. *Preview* is in the page header. |
| **What it may do in Jobber** | Create draft quotes, draft invoices, notes, a job from an approved quote, and a visit on a job (`ALLOWED_MUTATIONS` in `pumps.py`). It never sends anything to a client. Whether Jobber's API offers the job and visit actions is checked at run time; anything it can't do becomes a to-do. |
| **OpenClaw** | Off (`PUMPS_OPENCLAW=true` turns its API back on). |

The preview's old sheet rows (`pump_invoices`) were copied into items the first time the app started. The old table is left untouched.

## Setup (Railway → Office App → Variables)

| Variable | Needed for | What it does |
|---|---|---|
| `PUMPS_JOBBER_CLIENT_ID`, `PUMPS_JOBBER_CLIENT_SECRET` | Jobber | Keys from a Jobber app made for Pumps (see below). |
| `PUMPS_USE_CLAUDE` | optional | Off by default: Pumps reads Wettech's quotes (Word letters), invoices (PDF) and reports with its own reader, needs no Anthropic credits, and files and drafts on its own whatever it reads cleanly (a known vendor, an amount, and a client, PO or W/O). Anything else waits in the Inbox. `true` = use Claude (with the PO app's `ANTHROPIC_API_KEY`) for other vendors' layouts. |
| `OPENCLAW_API_KEY`, `PUMPS_OPENCLAW` | OpenClaw | Off unless `PUMPS_OPENCLAW=true`. |
| `PUMPS_DIGEST_TO`, `PUMPS_DIGEST_HOUR` | optional | The weekday morning email (simon@stahlman-england.com, 8). Needs Microsoft 365 *Mail.Send*. |
| `PUMPS_APPROVER` | optional | Name stamped on approved vendor quotes (Simon Weardon). |
| `PUMPS_AUTO_DRAFT_INVOICES` | optional | Draft our invoice when the vendor's bill arrives (on). |
| `PUMPS_USERS` | optional | e.g. `simon,beatriz`. Only these usernames can open Pumps. |
| `PUMPS_MARKUP_PCT` | unused | Invoices now use the quote markup: with our Jobber quote, its price; without one, the bill before tax plus 30% as one Service Proposal Amount line. |
| `PUMPS_QUOTE_MARKUP_PCT` | optional | Added to Wettech's price on client quotes (default `30`). |
| `PUMPS_AUTO_LOG_REPORTS` | optional | `false` = reports are only put in Jobber when someone clicks *Log in Jobber* (default `true`). |
| `PUMPS_DIVER_EMAIL`, `PUMPS_DIVER_NAME`, `PUMPS_DIVE_CC`, `PUMPS_DIVE_FROM`, `PUMPS_DIVE_EMAIL_AUTO` | optional | Defaults for the diver email (Gulfshoreyachts@gmail.com, Jordan, Andrea@stahlman-england.com, the PO mailbox, automatic sending on). All can be changed on the Accounts tab. Sending needs the Microsoft 365 app to be allowed to send mail (Mail.Send). |
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

Rebranded reports are made as PDFs too when LibreOffice is on the server. `nixpacks.toml` installs it on Railway (LibreOffice Writer, no GUI, plus Calibri/Arial-compatible fonts), which makes the image larger. Without it, reports go to Jobber as Word files.

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
