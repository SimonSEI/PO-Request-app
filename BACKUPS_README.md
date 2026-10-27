# Backups

The Office App keeps everything in one SQLite file, `/data/po_requests.db`. Uploaded
files (invoices, photos, receipts, pump reports, receivables files) are stored alongside it in `/data`.
`/data` is a Railway volume. If the volume is lost, corrupted or wiped, all of that is gone.

`backups.py` copies it all to separate storage:

| What | How often | Kept |
|---|---|---|
| The whole database (a consistent copy, checked, gzipped) | every 5 minutes if anything changed, at least daily | every copy for 2 days, then the last one each day for 90 days, then the last one each month |
| Uploaded files | new or changed files on the same 5-minute run | forever (never deleted from storage) |

If backups fail for 30 minutes, an alert goes to the Telegram chat (`TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`). A second message is sent when they recover.
Status, every copy and the restore buttons are on **/backups** (office logins; once
`CASHFLOW_USERS` is set, only those people, the same rule as for full-backup downloads).

## Where it goes

**Main storage:** the Railway bucket `office-app-backups` in the "po request app" project.
It is separate from the volume, so it survives the volume being lost, wiped or corrupted,
a bad deploy, or the service being deleted.

| Variable on the Office App service | Value |
|---|---|
| `BACKUP_S3_BUCKET` | `${{office-app-backups.BUCKET}}` |
| `BACKUP_S3_ENDPOINT` | `${{office-app-backups.ENDPOINT}}` |
| `BACKUP_S3_REGION` | `${{office-app-backups.REGION}}` |
| `BACKUP_S3_ACCESS_KEY_ID` | `${{office-app-backups.ACCESS_KEY_ID}}` |
| `BACKUP_S3_SECRET_ACCESS_KEY` | `${{office-app-backups.SECRET_ACCESS_KEY}}` |
| `BACKUP_S3_URL_STYLE` | `virtual-host` |

**Off-site storage (recommended):** the same variables with `BACKUP_OFFSITE_S3_` in front,
pointing at storage outside Railway (Cloudflare R2, Backblaze B2 or AWS S3). With both set,
every copy goes to both places, so you still have the data if the Railway account itself
is lost. For Cloudflare R2: create a bucket, create an API token with Object Read & Write on it,
then set `..._ENDPOINT` to `https://<account id>.r2.cloudflarestorage.com` and `..._REGION` to `auto`.

Other settings: `BACKUP_INTERVAL_MINUTES` (default 5) and `BACKUP_RESTORE_ON_EMPTY` (default true).

## Getting data back

**Something got deleted or broken, and the app is running.** Open /backups and click **Restore**
on a copy from before the problem. You type RESTORE to confirm. The current database is saved
first as a "saved before a restore" copy, so a restore can itself be undone. The app reloads on the
restored data.

**You have a downloaded copy.** On /backups, use **Restore from a file**. It accepts the `.db.gz`
from the Download button, a plain `.db`, or the `.zip` from the old "Create Backup" button
(uploads are limited to 50 MB).

**The volume is gone, or you're moving to a new Railway service or project.**
1. Create the service from this repo with a volume mounted at `/data` and `DATA_DIR=/data`,
   and copy the other variables (`SECRET_KEY`, Jobber, Microsoft, etc.).
2. Set the `BACKUP_S3_*` variables to the bucket that has the backups (or the off-site
   storage's details, if Railway's bucket is gone too).
3. Deploy. On start, the app sees there's no database, restores the newest copy, and then downloads
   all the files in the background. The deploy log shows
   `✓ Backups: empty volume - restored database from db/…`.
   If any files are missing afterwards, click **Restore missing files** on /backups.

**Railway is down and you need the data now, on any computer.**
```
pip install boto3 flask requests
export BACKUP_S3_BUCKET=… BACKUP_S3_ENDPOINT=… BACKUP_S3_REGION=… \
       BACKUP_S3_ACCESS_KEY_ID=… BACKUP_S3_SECRET_ACCESS_KEY=… BACKUP_S3_URL_STYLE=virtual-host
export DATA_DIR=./restored
python backups.py list                 # every copy, newest first
python backups.py restore --files      # newest copy + all files into ./restored
python backups.py restore db/20261013T185500Z.db.gz   # a particular copy
```
Add `--offsite` to read from the off-site storage instead. `--force` replaces an existing database,
saving the old one aside first. The bucket keys are in the Railway dashboard under the bucket's
Credentials tab. Keep a copy of them, and of the off-site keys, somewhere outside Railway
(a password manager).

## Tests

    python -m unittest tests.test_backups -v

Storage is faked with `moto` (`pip install "moto[s3]"`).
