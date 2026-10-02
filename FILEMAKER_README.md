# FileMaker (Features Coming Soon)

A working, browser-based recreation of a FileMaker Pro–style relational database builder,
opened from the **Features Coming Soon** folder on the dashboard. People in the office can
create a database file, design tables and relationships, draw layouts, write scripts, and
then use the result together, with records locked while someone edits them.

> **Independent recreation.** This is not a Claris product and is not affiliated with,
> endorsed by or sponsored by Claris International Inc. "FileMaker" and "Claris" are
> trademarks of Claris International Inc.; the name is used here only to describe what the
> prototype imitates. It is meant for prototyping and learning.

- **Who can open it:** office logins, or exactly the usernames in `FILEMAKER_USERS`.
  Technicians and property managers never can, whatever is set.
- **Code:** `filemaker.py` (the host: storage, accounts, privileges, locking, live updates)
  and `filemaker_assets/` (the FileMaker engine and interface, all in the browser). Hooked
  into `app.py` with `init_filemaker(app, csrf, DB_PATH, data_dir=DATA_DIR)`.
- **Data:** the app's SQLite database, in the `fm_*` tables. Files dropped into container
  fields are stored under `DATA_DIR/filemaker_files/<file id>/`.
- **Setup:** none. Optional: `FILEMAKER_USERS=simon,beatriz` to limit who sees it.

## How it fits together

| Piece | Where | What it does |
|---|---|---|
| Host | `filemaker.py` | Keeps each file's design (JSON), records, accounts and serial numbers. Checks the file's privilege sets on every read and write, locks records being edited, and sends each change to everyone else who has the file open (they poll `/changes` every 2 s). |
| Calculation engine | `fm-calc.js` | FileMaker's calculation language: parser, typed values (text, number, date, time, timestamp, container) and about 250 functions. |
| Data layer | `fm-data.js` | Relationships (multi-hop, multi-predicate), finds, sorts, summaries, validation, auto-enter, value lists, `ExecuteSQL`, and sync with the host. |
| Windows | `fm-render.js` | Browse, Find and Preview modes, Form/List/Table views, field controls, portals, tabs, popovers, charts, web viewers, record editing and report pagination. |
| Scripts | `fm-script.js` | The script step catalog, the runtime, the Script Workspace, the Script Debugger and the Data Viewer. |
| Dialogs | `fm-dialogs.js` | Manage Database (tables, fields, relationships graph), field options, Specify Calculation, value lists, custom functions, security, sort, import/export and the rest. |
| Layout mode | `fm-design.js` | The layout designer, inspector, object setup dialogs and the New Layout/Report assistant. |
| App | `fm-app.js`, `fm-starters.js` | Launch Center, starter solutions, window manager, menus and shortcuts, script triggers, printing. |

### Accounts and privileges

Each file has its own accounts, as in FileMaker. A new file gets a **[Full Access]** account
(named `Admin` unless you choose otherwise). With no password, the file signs in
automatically, and so does anyone who can open FileMaker here. Add a password to require
sign-in.

The host enforces privilege sets on every request. This covers record access per table
(view/edit/create/delete), field access (modifiable, view only, no access), schema changes
(Full Access only) and layout/script/value-list modify rights. **Record-level "limited"
access** is a calculation that the host evaluates for every record. It may use the record's
own fields, `Get ( AccountName )`, `Get ( AccountPrivilegeSetName )`, `Get ( UserName )`,
`IsEmpty`, `PatternCount`, `Lower`, `Upper`, `Trim`, `If`, `Case`, comparisons and
`and`/`or`/`not`. A privilege set using anything else is refused when it is saved, so a rule
is never only half enforced. A privilege set needs the `fmapp` extended privilege to open
the file.

### Multi-user behaviour

- Typing in a record takes the host's lock on it. Anyone else who types in it gets
  *"This record cannot be modified in this window because it is being modified by …"*.
- A record made with New Record exists on the host at once (so it has its serial number and
  record ID) but nobody else sees it until it is committed. Reverting it deletes it.
- Commits use the record's modification count. If the record changed underneath you, you are
  asked to revert rather than overwrite someone's work.
- Manage Database takes a schema lock, and Layout mode and the Script Workspace lock the
  layout or script being edited.
- File > Sharing lists who is connected. A Full Access user can message or disconnect them.
- Sessions that stop polling for 90 seconds are closed, and their locks and unsaved new
  records are released.

## What works

- **Database:** tables; text, number, date, time, timestamp, container, calculation and
  summary fields; repetitions; global fields. Auto-enter covers serials, creation and
  modification values, calculations, lookups, data and last-visited values. Validation covers
  strict type, not empty, unique, existing, value list, range, calculation, max characters,
  custom messages and override.
- **Relationships graph:** table occurrences; `= ≠ < ≤ > ≥ ×` predicates, including several
  per relationship; sorting; creating records through a relationship; cascading delete.
  Circular relationships are prevented, as in FileMaker.
- **Calculations:** text, number, date/time, aggregate, logical, JSON, financial,
  trigonometric, text formatting, repeating, design and `Get` functions; `Let`, `While`,
  `Evaluate`, custom functions with recursion, and `ExecuteSQL` (SELECT with joins,
  grouping, ordering and parameters).
- **Layouts:** edit boxes, drop-down lists, pop-up menus, checkbox and radio sets, calendars,
  concealed fields, text with merge fields and symbols, shapes, buttons, button bars,
  popovers, portals (filter, sort, delete, scroll), tab and slide controls, charts (column,
  bar, line, area, pie, donut, scatter), web viewers and pictures. Parts include title
  header/footer, header, footer, leading/trailing grand summaries and sub-summaries. There
  are six themes, conditional formatting, hide-when, tooltips, script triggers and tab order.
- **Layout mode:** drawing tools, drag and drop from the field list, move/resize/nudge,
  grouping, locking, arrange and align/distribute, undo/redo, cut/copy/paste, part resizing,
  an inspector, and setup dialogs for every object.
- **Modes and found sets:** Browse, Find, Layout and Preview modes; form, list and table
  views; FileMaker find operators (`= == ! < ≤ > ≥ ... // ? @ # * "" `); find, omit,
  constrain and extend; show omitted; Quick Find; saved finds; multi-key sort, including by
  value list order.
- **Scripts:** the FileMaker step catalog, with control flow, variables, parameters and
  results, error capture with `Get ( LastError )` and transactions. There are triggers
  (layout, object and file), button actions, a debugger with breakpoints, and a Data Viewer.
  Insert From URL is fetched by the host and refuses private or local addresses.
  `FileMaker.PerformScript` works from web viewer HTML.
- **Data in and out:** import from CSV, tab, Excel `.xlsx`, FileMaker XML and JSON (add,
  update in found set, update matching, or create a new table). Export to CSV, tab, Excel,
  FileMaker XML, JSON, HTML and merge. Save as Excel/PDF, and convert a spreadsheet into a
  new file.
- **Reports and printing:** sub-summary reports with subtotals, page headers and footers,
  page numbers, paper size, orientation, and printing or saving PDF through the browser.
- **Starter solutions:** Invoices, Contacts and Tasks & Projects, each with sample data.
- **Tools:** a Database Design Report (HTML), File Options (auto sign-in, opening layout,
  file triggers) and Save a Copy As (copy or clone).

## Coming soon (planned)

These appear in menus and the step list marked *(planned)* and do nothing yet:

- FileMaker WebDirect, the Data API / OData, and ODBC/JDBC sharing.
- FileMaker Cloud / Server admin console, Upload to Host.
- External SQL data sources (ESS) and Manage Containers.
- The themes and styles editor, custom menus and plug-ins.
- Data file steps (Create/Read/Write Data File), AppleScript, DDE and Send Event.
- AI steps (semantic find, models, embeddings) and the spelling steps (the browser's own
  spell checker is used instead).

Other limits to know about:

- Scripts run in the browser that started them. "Perform Script on Server" runs in that
  window too.
- Calculations use JavaScript numbers (about 15 significant digits), not FileMaker's
  arbitrary precision.
- Browsers keep some shortcuts for themselves (Ctrl+N, Ctrl+T, Ctrl+W in Chrome). Use the
  Records menu or the toolbar.

## Tests

```bash
python -m unittest tests.test_filemaker -v   # the host: files, accounts, privileges, locking, sync
node tests/filemaker_calc_test.js            # the engine: calculations, relationships, finds, SQL
```
