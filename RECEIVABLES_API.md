# Receivables API (for Grok Bot)

Grok Bot keeps the Receivables app up to date: it uploads the weekly QuickBooks A/R Aging Summary and records notes, payment ETAs, promises, retainage and project details. The office sees the result on the **Accounts** tab. Anything Grok Bot changes is noted as **"Grok Bot"**.

Receivables does not email customers (`AR_OUTREACH` is off); customer contact is Grok Bot's and the office's.

## Access

- **Base URL:** the Office App, e.g. `https://web-production-01609.up.railway.app`.
- **Key:** send `Authorization: Bearer <GROK_API_KEY>` on every call. The key is set on Railway (Office App → Variables → `GROK_API_KEY`). While it is unset the API answers 404; a wrong key gets 401.
- **Format:** JSON in and out. Every reply has `"success": true|false` and `"error"` when false.

## Weekly: upload the A/R sheet

```
POST /api/receivables/upload          (multipart/form-data)
  file     the QuickBooks A/R Aging Summary export (.xlsx or .csv)
  confirm  "1" to go ahead when the sheet would close more than half of what's open
```

- **What happens:** the summary's customers, aging and notes are stored, each customer's open invoices are found in Jobber, and accounts that drop off the sheet (or show $0 or a credit) are closed as paid.
- **Big drops:** if the sheet would close most of what's open, the reply is `{"needs_confirm": true, "missing": n, "open": m}`. Check the file, then send it again with `confirm=1`.
- **The A/R Aging Detail** (one row per invoice) is accepted too.

## Read

```
GET /api/receivables/accounts              every account owing, largest first
GET /api/receivables/accounts/<key>        one account
GET /api/receivables/invoices/<number>     one invoice: details, notes, emails, documents
GET /api/receivables/cash-in               money expected each week (13 weeks), late, no date
```

Each account has these fields:

| Field | What it is |
|---|---|
| `key` | The account's id, used in the update calls (`/accounts/<key>`). |
| `name` | The account's name. |
| `install` | `true` for construction/developer accounts (pay apps and proposals). |
| `sheet_total`, `aging` | The total and aging buckets from the latest sheet. |
| `as_of` | The date of that sheet. |
| `open_balance` | What's owing on the invoices here. |
| `retainage_held` | Retainage held across the account. |
| `past_due` | The amount past due. |
| `oldest_days_late` | Days late of the oldest invoice. |
| `next_expected` | The next date money is expected. |
| `sheet_notes` | The notes typed on the sheet. |
| `note` | The latest account note: `{at, by, text}`. |
| `projects` | Install accounts only, described below. |
| `invoices` | Service accounts only: the account's invoices. |

Each project has these fields:

| Field | What it is |
|---|---|
| `key` | The project's id, used in `/projects/<key>`. |
| `name` | The project's name, e.g. "Riverdale High School #222058". |
| `count`, `open_balance` | How many invoices are open and what's owing on them. |
| `retainage_held` | Retainage held on the project. |
| `retainage_state`, `retainage_text` | Where the retainage stands (states below). |
| `complete` | Whether the job is complete. |
| `note` | The project's note. |
| `next_expected` | The next date money is expected. |
| `invoices` | The project's invoices. |

`retainage_state` is one of:

| State | Meaning |
|---|---|
| `billing` | Invoices other than retainage are still open. |
| `held` | Everything is paid except retainage; held until the job is complete. |
| `held_ongoing` | The same, but the project is still going (from a note or a hold). |
| `due` | Everything is paid except retainage, and the job is complete: the retainage is due. |
| `none` | Nothing owed. |

Each invoice has these fields:

| Field | What it is |
|---|---|
| `number` | The invoice number, used in `/invoices/<number>`. |
| `txn_date`, `due_date` | The invoice date and due date. |
| `amount`, `open_balance` | The invoice total and what's still owing. |
| `retainage`, `retainage_pct` | Whether the balance is retainage, and its share of the total. |
| `days_late` | Days past due. |
| `status` | `open`, `promised`, `reported_paid`, `needs_person`, `paused` or `paid`. |
| `eta_date` | The ETA set by Grok Bot or the office. |
| `expected`, `expected_source` | When the money is expected, and where that date came from: `eta`, `promised`, `due` or `none`. |
| `jobber_subject`, `jobber_uri`, `client_hub_uri` | The Jobber subject, the Jobber link, and the customer's view-and-pay link. |

## Update

### An invoice

```
POST /api/receivables/invoices/<number>
{"note": "AP says check runs Friday",          // added to the invoice's history
 "eta": "2026-10-31",                          // money expected in hand ("" clears it)
 "action": "promise", "date": "2026-10-31",    // record a promise to pay
 "retainage": true,                            // true | false | "auto"
 "kind": "install"}                            // "install" | "service" | "auto"
```

`action` can be:

| Action | What it does |
|---|---|
| `promise` | Records a promise to pay; send the promised date as `date`. |
| `close` | Paid or written off. |
| `resume` | Back to open. |
| `pause` | Holds the invoice. |

### A project

```
POST /api/receivables/projects/<key>
{"note": "Closeout docs sent 10/20",
 "eta": "2026-11-15", "eta_retainage_only": true,   // ETA for all its open invoices, or its retainage only
 "complete": true,                                   // true | false | "auto" (from Jobber)
 "retainage_hold": false,                            // true = still going, don't treat retainage as due
 "last_furnished": "2026-10-01",                     // last day labor/materials furnished (lien deadline)
 "contact_name": "...", "contact_emails": "...", "owner_name": "...", "owner_email": "..."}
```

### An account

```
POST /api/receivables/accounts/<key>
{"note": "Spoke with AP, retainage at closeout",
 "type": "install",                  // "install" (construction/developer: projects) | "service" | "auto"
 "contact_name": "...", "emails": "ap@example.com"}
```

## Other

```
POST /api/receivables/run      run the hourly cycle now (Jobber look-ups, sheet notes)
```
