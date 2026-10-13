# Instructions for AI sessions

Start with `AI_CONTEXT.md` (the business, the system, the rules), then `worklog/README.md`
(status of every app) and the `worklog/<app>.md` file for the app you're changing.

After every change, in the same commit or PR:
- add a line to that app's **Work log** in `worklog/<app>.md`, and update its
  **Where it stands** / **Open threads** if they changed;
- update the status board in `worklog/README.md` if the app's status changed;
- run `python tools/build_worklog.py` (needs full history: `git fetch --unshallow` first in a
  shallow clone) to refresh the generated History sections.

Never make an app send anything to a client; Jobber writes are drafts only.
