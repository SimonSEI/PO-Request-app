> **Archived (October 2026).** The Work Orders app is switched off. Its code and tests are kept
> here for reference only: `workorders.py` is no longer imported by `app.py`, the dashboard tile
> is gone, `/workorders` and `/workorders/*` return 404, and the 15-minute inbox → Jobber → manager
> email cycle no longer runs, so no work order emails are forwarded or sent and nothing is written
> to Jobber. Existing rows in the `wo_inbox_communities`, `wo_inbox_orders`, `wo_inbox_tech_notes`,
> `wo_inbox_emails` and `wo_inbox_activity` tables, and the `workorders_*` settings, were left in
> the database untouched. The Railway variables `WORKORDERS_USERS` and `WORKORDERS_AUTO_RUN` are
> no longer read and can be deleted.
>
> To bring it back, move `workorders.py` to the repo root and `test_workorders.py` to `tests/`,
> then restore the `init_workorders` hook, the `workorders_ok` flag and the dashboard tile in
> `app.py` (see the commit that archived it).

# Work Orders

Community work orders from the inbox to Jobber to the community manager. See the docstring at
the top of `workorders.py` for how each cycle worked.

`visit-list-wip.patch` is unfinished work from before the archive, against the root-level
`workorders.py`: it lists the open work orders in the Instructions of the next visit on the
community's Jobber "WORK ORDER" job (one "20775-121641     8534 Karina Court" line each) and reads
the tech's notes from his job notes and finished visits. Its tests were not written yet.
