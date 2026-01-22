# 🚨 CRITICAL: Railway Persistent Storage Setup

## ⚠️ YOUR DATA IS BEING DELETED ON EVERY DEPLOYMENT!

**Problem:** Railway's filesystem is **ephemeral** - ALL files (including your database) are deleted on every deployment. This is why your jobs, PO requests, and invoices keep disappearing.

**Solution:** Configure a persistent volume RIGHT NOW to stop data loss.

---

## 📋 Quick Setup (5 minutes)

### Step 1: Add Volume in Railway

1. **Go to Railway Dashboard**: https://railway.app/dashboard
2. **Select your project**: PO-Request-app
3. **Click on your service** (the deployed app)
4. **Go to "Settings"** tab (or "Volumes" tab if available)
5. **Click "+ New Volume"** or **"Add Volume"**
6. **Configure**:
   ```
   Mount Path: /data
   Name: po-data
   ```
7. **Click "Add"** or **"Create"**

### Step 2: Verify It's Working

After Railway redeploys (2-3 minutes):

**Option A: Check Railway Logs**
- Go to **Deployments** → **View Logs**
- Look for: `✅ Using persistent data directory: /data`
- ✅ If you see this → **SUCCESS!** Data will persist
- ❌ If you see `⚠️ WARNING: PERSISTENT STORAGE NOT CONFIGURED!` → Volume not mounted correctly

**Option B: Check Health Endpoint**
- Visit: `https://your-app-url/health`
- Look for: `"persistent_storage": true`
- ✅ If true → **SUCCESS!**
- ❌ If false → Volume not configured

---

## ✅ What Gets Protected Once Volume is Configured

With the volume mounted at `/data`:

| Data Type | Location | Status |
|-----------|----------|--------|
| **Jobs** | Database | ✅ Will persist |
| **PO Requests** | Database | ✅ Will persist |
| **Users/Accounts** | Database | ✅ Will persist |
| **Invoice Files** | `invoice_uploads/` | ✅ Will persist |
| **Bulk Uploads** | `bulk_uploads/` | ✅ Will persist |

**Without the volume:** ❌ ALL of the above gets deleted on EVERY deployment!

---

## 🔍 Troubleshooting

### "I added the volume but data still disappears"

1. **Check mount path is exactly**: `/data` (lowercase, no trailing slash)
2. **Redeploy** after adding volume: Railway → Service → Settings → Redeploy
3. **Check logs** for the success message

### "Can I recover my deleted data?"

Unfortunately, no. Once deleted, the data is gone. You need to:
- Re-enter all jobs through Office Dashboard → Manage Jobs
- Re-enter any lost PO requests
- Re-register office accounts

---

## 🎯 Summary

**DO THIS NOW:**
1. ✅ Add Railway volume with mount path `/data`
2. ✅ Verify it's working (check logs or /health endpoint)
3. ✅ Re-enter your jobs and data (one-time)
4. ✅ From now on, all data persists across deployments

**Without this setup:**
- ❌ Every code change = data loss
- ❌ Every deployment = database reset
- ❌ Jobs, POs, invoices = deleted

**With this setup:**
- ✅ Code changes preserve data
- ✅ Deployments keep your database
- ✅ Jobs, POs, invoices = safe forever
