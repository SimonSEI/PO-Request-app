# Pump Manager: doing tasks and suggesting improvements

Pump Manager answers questions from the "Ask Pump Manager" panel in Pumps. Besides text, its answer can
**offer actions** (shown as buttons) and **ideas to improve the app**. Nothing is done until someone in
the office clicks **Do it**. The click runs the app's own route, so Jobber changes still need that
person's click, as everywhere else in the app.

## What Pump Manager receives

Every question POSTed to `PUMP_MANAGER_WEBHOOK_URL` now also carries:

- `how_the_app_works`: a short description of the workflow and tabs.
- `actions_you_can_offer`: each action type with what it does and its params.
- `reply_format`: how to answer.
- `context.case_id`: the watchlist item open in the panel, when there is one.

## How to answer

POST to `<WEBSITE_URL>/pumps/api/assistant/reply` with `Authorization: Bearer <PUMP_APP_REPLY_TOKEN>`:

```json
{
  "conversation_id": "...",
  "message_id": "...",
  "answer": "Found Jobber quote #9301 for Banyan Bay. Click below to track it.",
  "actions": [
    {"type": "track", "kind": "quote", "number": "9301"},
    {"type": "status", "case_id": 128, "kind": "waiting_vendor", "text": "Asked Tom for a date"}
  ],
  "suggestions": ["Read fiberglass tank quotes from Wettech too"]
}
```

`actions` and `suggestions` are optional, at most 5 of each. `label` is optional on an action and
replaces the button text.

## Action types

| type | params | does |
|---|---|---|
| `track` | `kind` (quote, job or request), `number` | Puts a synced Jobber record on the Job Watchlist |
| `link` | `case_id`, `kind` (quote, invoice or job), `number` | Links a Jobber record to a watchlist item |
| `unlink_invoice` | `case_id` | Takes a wrongly linked invoice off an item (nothing changes in Jobber) |
| `status` | `case_id`, `kind`, `text`, `on` (optional) | Posts a status update (`kind`: parts_ordered, waiting_vendor, client_notified, scheduled, in_progress, work_done, on_hold or note) |
| `urgent` | `case_id`, `on` | Moves a quote up with the jobs, or back down |
| `follow_up_tomorrow` | `case_id` | Postpones the vendor follow-up to the next working day |
| `done` | `case_id`, `note` | Marks an item done |
| `new_item` | `title` or `client_name`, plus `site`, `vendor` and `description` (optional) | Starts a new watchlist item |

The app checks each action when the answer arrives. An unknown type, a missing item, or a Jobber
number that isn't synced shows as "can't", with the reason. The app builds the route itself; it is
never taken from Pump Manager's answer. Deleting, marking bills paid, and sending emails are not
offered.

## Agent API: Pump Manager acting directly (Nov 2026)

Pump Manager can also read and act without a click. Every call carries
`Authorization: Bearer <PUMP_MANAGER_WEBHOOK_KEY>`, the same key the app sends with questions. Without that
key, or with a wrong one, the call gets a 401.

### Read

| GET | returns |
|---|---|
| `/pumps/api/agent/jobs?status=open\|all&q=` | Jobs with client, Jobber client and property, Jobber job #, linked quote/invoice/request, synced Jobber items, vendor bills, steps, status, to-dos |
| `/pumps/api/agent/jobs/<id>` | One job, plus its description, suggested quote matches and the last 50 history entries |
| `/pumps/api/agent/bills` | Vendor bills to pay and bills paid lately (read only) |
| `/pumps/api/agent/maintenance?month=YYYY-MM` | This month's maintenance visits and who has been told |
| `/pumps/api/agent/todos` | Open to-dos |
| `/pumps/api/agent/actions` | The action types and their params |

### Act

`POST /pumps/api/agent/actions` with `{"type": ..., "case_id": ..., ...}`. It takes the Ask panel's types
(above) and these:

| type | params | does |
|---|---|---|
| `link` | `case_id`, `kind` (quote, invoice, job or **bill**), `number` | Links a Jobber record by its #, or puts a vendor bill (by vendor invoice #) on the job |
| `add_note` | `case_id`, `text` | Adds a note to the job's history |
| `set_step` | `case_id`, `step`, `value` (`YYYY-MM-DD` done that day, `""` not done, `"na"` not needed) | Ticks, unticks or skips one step |
| `link_quote` | `case_id`, `number` | Links a synced Jobber quote, replacing an archived or wrong-client one |

`status` also takes `waiting_quote`, `quote_received` and `waiting_approval`.

The answer is `{"success", "action", "case_id", "undo_id"}`, or `{"success": false, "error"}` with a 400.

- Each action runs through the app's own route, the same one an office click uses, as the user **"Pump Manager"**.
  It is logged in the job's history as "Pump Manager action: <what>".
- Each action goes on the Undo list (24 hours), labelled with Pump Manager's name. Office users can undo it there.
  Pump Manager can undo its own actions with `POST /pumps/api/agent/undo {"undo_id"}`, but not anyone else's.
- **Never allowed:** deleting, marking bills paid (or unpaid, or on hold), and sending email. These are refused
  even if an action would lead to one of those routes.
- Jobber is still only changed by a person's click. Routes that write to Jobber (drafting a quote or an
  invoice, adding a Jobber note) refuse Pump Manager the same way they refuse the mailbox scan.
