# 🧪 Gmail Polling Local Testing Guide

**Phase 2 Complete**: Gmail polling, task extraction, and API endpoints  
**Status**: Ready for local testing  
**Estimated Test Time**: 30-45 minutes  

---

## 📋 **Pre-Testing Checklist**

### **1. Generate Encryption Key** (Do this first!)
```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Output**: `gAAAAABl...` (long string)

**Save this** - you'll add it to `.env`

---

### **2. Update `.env` File**

**File**: `C:\Users\bhaga\Desktop\joshu\backend\.env`

Add these variables (copy from .env.example, then fill in):

```env
# OAuth (you should already have these from Phase 1)
GOOGLE_CLIENT_ID=YOUR_WEB_CLIENT_ID_HERE
GOOGLE_CLIENT_SECRET=YOUR_WEB_CLIENT_SECRET_HERE
GOOGLE_REDIRECT_URI=http://localhost:8000/auth/callback

# Gmail Polling (NEW - from Phase 2)
ENCRYPTION_KEY=paste-your-generated-key-here
GMAIL_POLLING_ENABLED=true
GMAIL_POLL_INTERVAL_MINUTES=15
GMAIL_MAX_MESSAGES_PER_POLL=25
```

**Important**: Replace placeholder values with your actual Google credentials

---

### **3. Update Google Cloud Console**

Add these scopes to your OAuth consent screen (if not already there):

```
openid
email
profile
https://www.googleapis.com/auth/gmail.readonly
```

---

## 🚀 **Testing Steps**

### **Step 1: Restart Backend**

Stop the old backend process (still running from this morning):

```bash
# Find and kill the old uvicorn process
Get-Process | Where-Object {$_.ProcessName -like "*python*"} | Stop-Process -Force

# Start fresh backend
cd C:\Users\bhaga\Desktop\joshu\backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

**Expected Output**:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
INFO:     Scheduler initialized and running every 15 minutes
```

**Key**: Watch for "Scheduler initialized" message

---

### **Step 2: Verify Backend Ready**

```bash
# Check health endpoint
curl http://localhost:8000/health

# Check Swagger docs
# Open in browser: http://localhost:8000/docs
```

**Expected**: Health returns `{"status":"ok"}`

---

### **Step 3: Start Flutter Frontend**

```bash
cd C:\Users\bhaga\Desktop\joshu\app
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
```

**Expected**: Browser opens to localhost:8000 or similar

---

### **Step 4: Sign In (OAuth Flow)**

1. Click "Sign in with Google"
2. Browser/webview opens Google login
3. **IMPORTANT**: You'll see consent screen asking for:
   - `email`
   - `profile`
   - `Gmail read-only access`
4. Click "Allow" to approve **all scopes including Gmail**
5. App navigates to home screen

**Key**: Make sure you approve the Gmail scope!

---

### **Step 5: Trigger Gmail Polling**

**Option A** (Automatic - wait 15 seconds):
- Just wait. Background scheduler runs every 15 minutes.
- After 15 seconds, check tasks endpoint

**Option B** (Immediate - recommended for testing):
```bash
# Call the sync endpoint directly
curl -X POST http://localhost:8000/tasks/sync \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN_HERE"
```

**How to get YOUR_SESSION_TOKEN**:
1. After sign-in, check browser DevTools (F12)
2. Go to Application → Local Storage
3. Look for session token (or check terminal output)

**OR**: Call via API:
```bash
curl http://localhost:8000/health  # Just to test connectivity
```

---

### **Step 6: Fetch Tasks**

```bash
curl http://localhost:8000/tasks \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN_HERE"
```

**Expected Response**:
```json
{
  "tasks": [
    {
      "id": "uuid-here",
      "user_id": 1,
      "title": "Team Standup",
      "description": "Organizer: manager@company.com\nAttendees: you, colleague1, colleague2\nLink: https://meet.google.com/xxx",
      "scheduled_for": "2026-11-25T10:00:00Z",
      "source": "email",
      "status": "pending",
      "organizer": "manager@company.com",
      "attendees": ["manager@company.com", "colleague1@company.com"],
      "calendar_event_link": "https://meet.google.com/xxx",
      "created_at": "2026-11-24T15:50:00Z"
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

**Success Criteria**:
- ✅ Tasks array has at least 1 item
- ✅ Title extracted correctly
- ✅ Date/time is correct
- ✅ Attendees listed
- ✅ Meeting link present

---

## ✅ **Success Criteria**

| Check | Expected | Status |
|-------|----------|--------|
| Backend starts | No errors, scheduler running | ✅ |
| OAuth sign-in | Approves Gmail scope | ✅ |
| Session created | Token stored securely | ✅ |
| Polling runs | Finds Gmail invitations | ✅ |
| Tasks extracted | Title, time, attendees | ✅ |
| API returns tasks | JSON with task list | ✅ |
| Deduplication | Same email = 1 task | ✅ |
| No data leaks | No tokens in logs | ✅ |

---

## 🐛 **Troubleshooting**

### **Error: "ENCRYPTION_KEY not configured"**
```
Solution: Add ENCRYPTION_KEY to .env and restart backend
```

### **Error: "scope_upgrade_required" on /tasks/sync**
```
Solution: User didn't approve Gmail scope during sign-in
  → Sign out
  → Sign in again
  → Explicitly approve all scopes including Gmail
```

### **Error: "google_token_expired" on /tasks/sync**
```
Solution: Google refresh token is invalid
  → User should disconnect and re-authenticate
  → (Phase 3 will handle reconnection UI)
```

### **Tasks not appearing**
```
Troubleshooting steps:
1. Check /auth/me endpoint:
   curl -H "Authorization: Bearer TOKEN" http://localhost:8000/auth/me
   
2. Verify gmail.readonly scope is in response:
   Look for: "granted_scopes": "openid email profile gmail.readonly"
   
3. Check if Gmail has invitations:
   Go to your Gmail inbox directly
   Search for emails with subject containing "Invitation:"
   
4. Run sync manually:
   curl -X POST http://localhost:8000/tasks/sync \
     -H "Authorization: Bearer TOKEN"
   
5. Check backend logs:
   Look for "GmailPollingScheduler" or "SyncResult" messages
```

### **Backend won't start**
```
Error: "Address already in use"
Solution: Kill old process:
  Get-Process | Where-Object {$_.ProcessName -like "*python*"} | Stop-Process -Force
```

### **Flutter can't reach backend**
```
Error: "Failed to reach http://localhost:8000"
Solution: 
  1. Check backend is running: curl http://localhost:8000/health
  2. Check CORS origins in .env includes your Flutter dev URL
  3. Check firewall allows port 8000
```

---

## 📊 **Testing Checklist**

- [ ] Generated ENCRYPTION_KEY
- [ ] Updated .env with encryption key
- [ ] Updated .env with Gmail polling settings
- [ ] Restarted backend
- [ ] Backend shows "Scheduler initialized" message
- [ ] Signed in via OAuth
- [ ] Approved **Gmail scope** during sign-in
- [ ] Called POST /tasks/sync (or waited 15 seconds)
- [ ] Called GET /tasks
- [ ] Saw extracted meeting tasks
- [ ] Tasks have title, time, attendees, link
- [ ] Tried calling sync twice → no duplicates
- [ ] Checked backend logs for errors

---

## 📝 **What to Document After Testing**

Write down:
1. **Number of tasks extracted** (from GET /tasks response)
2. **Sample task title** (what meetings were found)
3. **Any errors** (and how you fixed them)
4. **Performance** (how long polling took)
5. **Any issues** (unexpected behavior)

---

## ⏭️ **What's Next**

Once Gmail polling is verified working:

1. **Wait for Neon** to build Phase 3 (Approval UI)
   - Add buttons to approve/reject tasks
   - Update task status in database
   - Show current status to user

2. **Or provide Neon with Phase 3 prompt** (I can write it)

---

## 🎯 **Quick Test Command Reference**

```bash
# Health check
curl http://localhost:8000/health

# Get current user
curl -H "Authorization: Bearer TOKEN" http://localhost:8000/auth/me

# List tasks
curl -H "Authorization: Bearer TOKEN" http://localhost:8000/tasks

# Trigger sync immediately
curl -X POST -H "Authorization: Bearer TOKEN" http://localhost:8000/tasks/sync

# Check sync status
curl -H "Authorization: Bearer TOKEN" http://localhost:8000/tasks/sync/status

# Swagger docs
# Open: http://localhost:8000/docs
```

---

## 🚀 **Ready to Test?**

1. Generate encryption key (copy output)
2. Update `.env` file (paste key + Gmail settings)
3. Restart backend
4. Sign in via Flutter
5. Approve Gmail scope
6. Check GET /tasks
7. Document results

**Estimated time: 30-45 minutes**

Good luck! 🎉
