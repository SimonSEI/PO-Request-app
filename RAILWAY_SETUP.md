# Railway Persistent Storage Setup

## ⚠️ CRITICAL: Your database is being reset on every deployment!

Railway's filesystem is **ephemeral** - files are deleted when your app redeploys. This is why your jobs data disappeared.

## Solution: Add a Persistent Volume

Follow these steps to prevent future data loss:

### 1. Add a Volume in Railway

1. Go to your Railway project dashboard
2. Click on your service (PO-Request-app)
3. Click the **"Variables"** tab
4. Scroll down and click **"+ New Volume"**
5. Configure the volume:
   - **Mount Path**: `/data`
   - **Name**: `po-data` (or any name you prefer)
6. Click **"Add"**

### 2. Redeploy Your App

After adding the volume, Railway will automatically redeploy your app. The database and uploads will now persist across deployments.

### 3. Verify Persistent Storage

After redeployment:
- Check the Railway logs for: `✓ Using persistent data directory: /data`
- If you see: `⚠ Using local data directory`, the volume isn't mounted correctly

## What Gets Saved in the Volume

With the volume mounted at `/data`, these will persist:
- ✅ Database (`po_requests.db`) - All jobs, PO requests, users
- ✅ Invoice uploads (`invoice_uploads/`)
- ✅ Bulk uploads (`bulk_uploads/`)

## Restoring Your Lost Jobs

Unfortunately, the jobs that were deleted cannot be automatically recovered. You will need to:

1. Re-add your jobs through the Office Dashboard → Manage Jobs
2. Or contact your database administrator if you have backups

## Alternative: Use PostgreSQL

For production use, consider using Railway's PostgreSQL database instead of SQLite:
- More robust for concurrent users
- Built-in backups
- Better performance
- Automatic persistence

Contact your developer to migrate from SQLite to PostgreSQL if needed.
