# Vendor Invoices

The **Vendor Invoices** tile (under *Features Coming Soon* on the dashboard) is the `CURRENT VENDOR INVOICES` workbook as an app, for every non-pump vendor (sub contractor) invoice that comes into PO@Stahlman-England.

- **Who can open it:** office and admin logins, or only the usernames in `VI_USERS`.
- **Code:** `vendor_invoices.py` (logic and API), `vendor_invoices_page.py` (the page), hooked into `app.py` with `init_vendor_invoices(...)`. Tables start with `vib_`. PDFs from PO@ are kept in `<DATA_DIR>/vendor_invoice_files/`.
- **Tests:** `python -m unittest tests.test_vendor_invoices -v`

## The sheet

- One tab per month along the bottom, newest first, with the workbook's columns A–P: OK TO PROCESS?, SUB CONTRACTOR, INVOICE DATE, INVOICE #, INVOICE TOTAL, SEI PROPOSAL #, DATE BILLED, AMOUNT SEI BILLED, NOTES, PROJECT MGR, INVOICE TO CHRISTIAN, BILL.COM, EXPECTED PAYMENT DATE (and the thin gray spacer columns F, K, O).
- **Everything in the workbook is here.** The first time the app starts it imports `vendor_invoices_seed.json`, made from the workbook: all 80 month tabs (March 2020 → October 2026), every cell, the fill colors, bold and red text, merged cells, and each tab's own header row (older tabs still say *INVOICE TO JOANNE*). Only the empty *MASTER COPY BLANK* tab is left out; **+** on the tab bar makes a new month. The old tabs' `=SUM` rows are kept as rows; each tab also shows a live *TAB TOTAL*.
- **Editing works like Excel:** click a cell and type; Enter saves and moves down, Tab moves right, Esc cancels, Delete clears, Ctrl+B bolds. Dates can be typed `9/17/26`; anything that isn't a date (`TBD OCT 20`) is kept as typed. YES in *OK TO PROCESS?* turns green and NO red, as on the sheet. The fill colors are the sheet's (green, blue, yellow, red, mint, pink).
- **Search** looks through every month at once.
- **Download .xlsx** gives the whole thing back as a workbook laid out like the original. **Upload workbook** brings in tabs from a workbook (tabs already here are skipped unless *Replace* is ticked).

## Invoices that came into PO@

Every hour the app reads new mail in PO@ (from the date on Settings) and looks at each PDF:

- **Pump vendors are skipped** — Wettech / Wet Tec / W.E.T. stay in the Pumps app. The list is on Settings.
- The PDF is read (Claude when it's on, simple rules otherwise) for vendor, invoice #, date, total and proposal #.
- **From a vendor on the sheet** (Pelican Lawn, Sanchez Sod, Mongoven, Graber, …) → listed as *waiting to be entered*.
- **From anyone else** → listed separately and not counted until someone clicks *It's a vendor invoice* or *Not a vendor invoice*. The answer is remembered for that sender.
- **Enter on [tab]** adds a row to the open tab, filled in from the PDF. Typing a row by hand with the same vendor and invoice # counts too.

**Invoice never entered:** a vendor invoice still not on the sheet after 3 days (Settings) is emailed to Christian in one list, and again every 7 days while it's still not entered.

## Jobber

The **JOBBER INVOICE** column (Q) is new. A person links each row to the SEI invoice in Jobber it was billed on: *Link…* searches Jobber (when the notes say `INV 36437` it offers that number first). Every hour each linked invoice is checked; **when Jobber shows it paid, Christian is emailed once**, so the vendor can be paid. Linking an invoice that is already paid asks before emailing. Jobber is only read (`_jobber` refuses any change), through the Jobber app connected in Pumps.

Emails are sent from PO@ through Microsoft 365, to Christian's address on Settings (the same setting the older vendor invoice preview used, `CHRISTIAN_EMAIL` by default).
