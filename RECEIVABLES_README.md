# Receivables

The Receivables tile in The Office App chases open invoices from the QuickBooks A/R sheet. It sends past-due follow-ups (with the invoice and any install documents attached), reads replies, tracks retainage by job, and watches lien deadlines on install jobs.

- **Who can open it:** office logins, or only the usernames in `AR_USERS`. Technicians and property managers never can.
- **Code:** `receivables.py` (logic and API), `receivables_page.py` (the page). It is hooked into `app.py` with `init_receivables(...)` and uses the same SQLite database, in tables starting `ar_`. Uploaded documents are kept in `<DATA_DIR>/receivables_files/`.

## How it works

1. **Upload the A/R sheet.** In QuickBooks run *Reports → A/R Aging Detail* (or *Open Invoices*), export to Excel, and click **Upload QuickBooks A/R**. The upload is the list of what is owed:
   - Invoices that are new get added.
   - Lower balances are noted as payments.
   - Invoices that are no longer on the sheet are closed as paid and their follow-ups stop.
   - If a file would close more than half of what's open, the app asks first (in case it's not the full list).
   - Payments, credit memos and $0 lines are skipped.
   **Or upload your A/R Aging Summary with your notes.** This is the sheet with one row per customer and CURRENT / 1 - 30 / 31 - 60 / 61 - 90 / 91 AND OVER columns, with notes typed into free cells. The app recognises it by itself.
   - **Invoices:** the summary has no invoice numbers, so each customer's open invoices are found in Jobber by name. QuickBooks and Jobber names match because Jobber syncs them. The search stops once they add up to the customer's total on the sheet.
   - **Amounts inside notes:** a note typed over an amount keeps that amount ("releases signed for these so on its way 35120").
   - **Paid customers:** a customer who drops off the sheet, or shows $0 or a credit, is closed as paid.
   - **When Jobber doesn't match:** a customer whose Jobber total differs from the sheet is listed under *Needs a person*.
   - **Your notes are read (Claude, or simple rules without it) and acted on:**

     | Your note says | What the app does |
     |---|---|
     | "paid today", "card charged" | Waits for it to clear |
     | "check coming", "preparing a check", "will pay by EOM" | Payment promised: no follow-ups until very past due |
     | "awaiting board approval", "waiting on funding" | Snoozes 14 days |
     | "disputing" | *Needs a person* |
     | "followed up no response" | Counts as a follow-up on the sheet's date, so nobody gets a second email right away |
     | "follow up again if not received by the 12th", "wait one more week" | Snoozes until then |
     | "retainage ongoing, can't collect" | Puts that customer's retainage on hold |
     | "All retainage" in the Total column | Marks all of the customer's invoices as retainage. In an aging column it covers only that column. |

   - **Where notes show:** on the customer (Customers tab), under the customer in the Invoices list, and in each invoice's breakdown.
   - **Re-uploading:** only new or changed notes are acted on, so you can keep updating the same sheet and upload it each week.
2. **Jobber (hourly).** Each open invoice is found in Jobber by its number. That gives the client's email addresses, the *client hub* link where the customer can view and pay, the line items, the Jobber job, whether the job is complete, and whether Jobber already shows it paid. Jobber is only read, never changed (`_jobber` refuses any mutation). It uses the Jobber app connected in Pumps.
3. **Service call or install.** An invoice is an **install** when its subject, memo, line items or QuickBooks sub-customer mention any of the words on Settings (`pay app, install, installation, proposal, retainage, retention`), or when it is retainage. Otherwise it is a **service call**. Every invoice on a job with an install invoice is an install too. Invoices are grouped into jobs in this order:
   1. The Jobber job.
   2. The project code on the line item, e.g. `26106 - TIDE CLEANERS`.
   3. The name after "PAY APP 1 -".
   4. The QuickBooks sub-customer (`Builder:Project`).

   Type, retainage and job can all be set by hand on the invoice.
4. **Retainage.** An invoice paid all but 5% or 10% (± 0.6 points; percentages on Settings) is retainage. The Jobs tab totals it per job. Retainage isn't chased while the job is open. Once the job is complete (Jobber marks it complete, or you set it on the job) a *Retainage release* email goes out every 30 days.
5. **Follow-ups.** Due follow-ups are grouped into one email per install job and one per customer for service calls. They are sent from **simon@stahlman-england.com** (Settings → *Send from*; any mailbox in the Microsoft 365 tenant works). The tone gets firmer the later the invoice is:

   | Stage | Starts (days past due) | Repeats every |
   |---|---|---|
   | Friendly reminder | 1 | 14 days |
   | Past due | 31 | 10 days |
   | Very past due | 61 | 7 days ("we have preserved our lien rights" on installs) |
   | Final notice | 91 | 5 days (installs: Notice of Nonpayment and lien to follow) |

   Attachments:
   - **Service calls:** each invoice as a PDF, made from Jobber's line items. If you uploaded the invoice PDF on the invoice, that is sent instead.
   - **Installs:** the same, plus every document uploaded on the job.
   - **Everyone:** documents uploaded on a customer, or as "every email", go with all their emails.
6. **Replies.** The sending mailbox's inbox is read every hour. A reply is matched to our email's conversation, or to a customer's known address when it mentions an invoice or payment. Mail from anyone else is ignored and not stored. Each reply is read by Claude (or simple rules without `ANTHROPIC_API_KEY`):
   - **"Payment is coming"**: no more follow-ups until the invoice reaches *very past due* (61 days). If it is already that late, the app waits until the date they gave plus 7 days.
   - **"We paid"**: waits 14 days for it to show up on an upload or in Jobber, then resumes.
   - **Dispute, question, wrong contact, anything else**: follow-ups stop and the invoice goes to *Needs a person* on Today.
   - **Out of office**: ignored. **Bounced email**: *Needs a person* until the address is fixed.
7. **Liens and the Notice of Nonpayment (NONP).** For install jobs the lien deadline is the last day furnished + 90 days (Florida, Chapter 713). The last day furnished comes from the date on the job, else Jobber's completion date, else the latest invoice date (shown as *estimated*). When money on the job is past due and the deadline is 30 days away:
   - The app prepares a Notice of Nonpayment PDF and a draft email to the property owner (cc the contractor), saying a claim of lien will follow.
   - With *Email the Notice of Nonpayment automatically* on, the email is sent.
   - The job then walks through *sent → mailed certified → lien recorded*.
   - If the customer looks like a contractor (builder, construction, landscape...), the owner must be entered on the job first.
   - A last day furnished that is only estimated from the last invoice date shows on the Jobs tab, but never raises an alert or prepares a notice. Enter the real date on the job once the work is finished.

### What the app does not do

- **It does not record the lien.** Recording is done with the county.
- **It does not mail the notice certified.** Florida service of these notices is by certified mail or delivery, and email alone doesn't count. The Lien deadlines list on Today keeps reminding until both are marked done.
- **The notice's wording needs an attorney's check before it's relied on.**

## Going autonomous

Out of the box follow-ups and notices wait as drafts on **Today**, so the first upload doesn't email every customer at once. Once the drafts look right:

- Settings → **Send follow-ups automatically** (sends Monday–Friday within *Automatic sending hours*, 8–17 by default).
- Settings → **Email the Notice of Nonpayment automatically**.

Everything else (Jobber, replies, retainage, lien deadlines) runs on its own every hour. **Run now** runs it immediately.

## Setup (Railway → Office App → Variables)

| Variable | Needed for | What it does |
|---|---|---|
| `MS_TENANT_ID`, `MS_CLIENT_ID`, `MS_CLIENT_SECRET` | email | The Microsoft 365 app the PO app already uses. It needs **Mail.Send** and **Mail.Read** (application) for the sending mailbox. If the tenant limits the app to certain mailboxes (an application access policy), add simon@stahlman-england.com to it. |
| Pumps' Jobber connection | Jobber | Connect Jobber on the Pumps page. Receivables reads invoices, clients and jobs through it. |
| `ANTHROPIC_API_KEY` | optional | Lets Claude read replies. Without it, simple rules do. |
| `AR_FROM_EMAIL` | optional | Default "send from" address before Settings is saved (simon@stahlman-england.com). |
| `AR_USERS` | optional | e.g. `simon,beatriz`. Only these office usernames can open Receivables. |
| `AR_AUTO_RUN` | optional | `false` stops the hourly cycle (*Run now* and uploads still work). |

## Tests

```
pip install -r requirements.txt
python -m unittest tests.test_receivables -v
```

The tests use a throwaway database, a made-up QuickBooks export, and fake Microsoft 365 and Jobber connections. Run each suite on its own (`tests.test_pumps` and `tests.test_workorders` already disagree when run in one process).
