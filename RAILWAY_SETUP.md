# Railway Setup for Persistent Data

This guide explains how to configure Railway to **prevent data loss** when updating/redeploying your app.

## The Problem

By default, Railway uses an **ephemeral filesystem** - meaning all files (including your SQLite database) are deleted whenever you:
- Deploy a new version
- Restart the app
- Scale the app

## The Solution: Railway Volumes

Railway Volumes provide persistent storage that survives deployments.

### Step 1: Create a Volume in Railway Dashboard

1. Go to your project in the [Railway Dashboard](https://railway.app/dashboard)
2. Click on your service (the one running this app)
3. Go to the **Settings** tab
4. Scroll down to **Volumes**
5. Click **Add Volume**
6. Set the **Mount Path** to: `/data`
7. Click **Create Volume**

### Step 2: Add the Environment Variable

1. Still in your service settings, go to the **Variables** tab
2. Add a new variable:
   - **Name**: `DATA_DIR`
   - **Value**: `/data`
3. Click **Add** or save

### Step 3: Redeploy

1. Railway will automatically redeploy with the new volume
2. Your database and uploaded files will now persist across deployments

## Verification

After setup, you should see these logs when your app starts:
```
✓ Using data directory: /data
✓ Database path: /data/po_requests.db
```

## Important Notes

- **First deployment after setup**: Your existing data from before adding the volume will NOT be migrated automatically. You may need to re-enter your data once.
- **Volume size**: Railway volumes start at 1GB by default (expandable)
- **Backups**: Consider periodically backing up your data - volumes are persistent but not backed up by Railway

## Troubleshooting

### Data still being lost?
- Verify the `DATA_DIR` environment variable is set to `/data`
- Check that the volume is mounted at `/data`
- Look at deploy logs for the "Using data directory" message

### Can't connect to database?
- Ensure the `/data` directory is writable
- Check Railway logs for any permission errors
