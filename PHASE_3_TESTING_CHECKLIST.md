# ✅ Phase 3 Completion Checklist

**Expected Arrival**: ~7:30 PM IST (3-4 hours from now)

---

## 📥 **Step 1: Pull Phase 3 Changes** (5 min)

```bash
cd C:\Users\bhaga\Desktop\joshu
git fetch origin
git status

# Should show feature/phase-3-approval-ui branch available
# Pull it:
git pull origin feature/phase-3-approval-ui

# Or if it's on main:
git pull origin main
```

Verify changes downloaded:
- Backend files updated
- Frontend files updated
- Database migrations present

---

## 🧪 **Step 2: Verify Backend Still Running** (2 min)

```bash
# Check if backend is still running
curl http://localhost:8000/health
# Should return: {"status":"ok"}

# If not running:
cd C:\Users\bhaga\Desktop\joshu\backend
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

---

## 🌐 **Step 3: Run Flutter Web App** (5-10 min)

```bash
cd C:\Users\bhaga\Desktop\joshu\app

# Option A: Via VS Code (Recommended)
# Press: Ctrl+Shift+P
# Type: Flutter: Run Web
# Press: Enter

# Option B: Via Terminal (if Flutter is now installed)
flutter run -d web
```

**Wait for browser to open** (~2-3 minutes on first build)

---

## 🔐 **Step 4: Sign In** (2-3 min)

1. Click: **[Sign in with Google]**
2. Browser opens Google login
3. Sign in with your Gmail account
4. **Approve Gmail Scope** ← Important!
5. App navigates to dashboard

---

## ✅ **Step 5: Verify Phase 3 Features**

### **Task List Screen**
Check these appear:
- [ ] Dashboard title visible
- [ ] "Filter:" buttons appear (All, Pending, Approved, Rejected)
- [ ] At least 1 task card visible
- [ ] Task card shows: Title, Date/Time, Organizer, Attendees

### **Task Card Content**
- [ ] Meeting title (e.g., "Team Standup")
- [ ] Date and time (e.g., "Tue, Nov 25, 2026 • 10:00 AM")
- [ ] Organizer email
- [ ] Number of attendees or attendee list
- [ ] Meeting link (if available)
- [ ] Status badge (should show "pending" initially)

### **Buttons on Task Card**
- [ ] [Approve] button visible
- [ ] [Reject] button visible
- [ ] [Details] button visible (optional)

---

## 🎯 **Step 6: Test Approve Function** (2 min)

1. **Click [Approve] on any task**
2. Wait for loading animation
3. **Expected Result**:
   - ✅ Toast message: "Task approved!"
   - ✅ Task card status changes to "✓ Approved" (green)
   - ✅ Buttons become disabled/hidden
4. **In Filter**: Task moves to "Approved" section

**Troubleshooting**:
- Error message? Check console (F12)
- Task didn't update? Refresh page - should still show approved
- Button didn't respond? Check backend is running

---

## 🎯 **Step 7: Test Reject Function** (2 min)

1. **Click [Reject] on another task**
2. **Dialog appears** asking to confirm rejection
3. **Optional**: Type rejection reason (e.g., "Already have this scheduled")
4. Click [Reject] button in dialog
5. Wait for loading
6. **Expected Result**:
   - ✅ Toast message: "Task rejected"
   - ✅ Task card status changes to "✗ Rejected" (red)
   - ✅ If reason provided, it's saved
   - ✅ Buttons become disabled/hidden
7. **In Filter**: Task moves to "Rejected" section

---

## 🎯 **Step 8: Test Filtering** (2 min)

1. **Click [Pending]** filter
   - Should show only tasks with status = "pending"
   - Approved/Rejected tasks hidden
   
2. **Click [Approved]** filter
   - Should show only tasks with status = "approved"
   - Should see the task you approved
   
3. **Click [Rejected]** filter
   - Should show only tasks with status = "rejected"
   - Should see the task you rejected
   
4. **Click [All]** filter
   - Should show all tasks (pending + approved + rejected)

---

## 💾 **Step 9: Test Persistence** (2 min)

1. **Approve/reject some tasks**
2. **Refresh page** (F5 or Ctrl+R)
3. **Wait for page to reload**
4. **Expected**: Tasks still show approved/rejected status
   - Status should persist from database
   - If status is gone → Something went wrong

---

## 📋 **Step 10: Test Details Modal** (Optional, 1 min)

1. Click **[Details]** button on any task
2. Modal should open showing:
   - Full meeting title
   - Full date/time
   - Organizer info
   - Full attendee list
   - Meeting link (clickable)
   - Full description/email body
3. **Click meeting link** → Should open in new tab
4. **Click [Close]** → Modal closes

---

## 🧪 **Backend Verification** (Optional, 5 min)

Test API endpoints directly:

```bash
# 1. Get all pending tasks
curl -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  http://localhost:8000/tasks?status=pending

# 2. Get approved tasks
curl -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  http://localhost:8000/tasks?status=approved

# 3. Get single task details
curl -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  http://localhost:8000/tasks/{task_id}

# 4. Approve task (via API)
curl -X POST \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  http://localhost:8000/tasks/{task_id}/approve

# 5. Reject task (via API)
curl -X POST \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"reason":"Already scheduled"}' \
  http://localhost:8000/tasks/{task_id}/reject
```

**Expected**: All endpoints return 200 OK with updated task data

---

## ✅ **Success Checklist**

| Item | Status |
|------|--------|
| Phase 3 code pulled into VS Code | ☐ |
| Backend still running | ☐ |
| Flutter web app starts | ☐ |
| Can sign in with Google | ☐ |
| Dashboard shows tasks | ☐ |
| Can approve a task | ☐ |
| Can reject a task | ☐ |
| Can filter by status | ☐ |
| Status persists after refresh | ☐ |
| No errors in console | ☐ |

---

## 🐛 **If Something Goes Wrong**

### **"Tasks not loading"**
```bash
1. Check backend: curl http://localhost:8000/health
2. Check browser console: F12 → Console tab
3. Check network tab: Look for /tasks requests
4. Restart backend if needed
```

### **"Approve/Reject not working"**
```bash
1. Check console for errors: F12
2. Verify session token exists
3. Try via curl first (see step above)
4. Check backend logs for errors
```

### **"Status not persisting"**
```bash
1. Refresh page and check if approved_at is in response
2. Query database: SELECT * FROM tasks WHERE id = 'xxx'
3. Verify timestamp was set
```

### **"Can't sign in"**
```bash
1. Check backend health: curl http://localhost:8000/health
2. Check OAuth configuration
3. Make sure Gmail scope was approved
4. Try signing out and back in
```

---

## 📸 **Document Screenshots/Results**

After testing, document:
- **Number of tasks**: How many were extracted?
- **Number approved**: How many did you approve?
- **Number rejected**: How many did you reject?
- **Any errors**: Copy/paste any error messages
- **Performance**: Did it feel responsive?

---

## 🎉 **If All Tests Pass**

You're ready for Phase 4! Which includes:
- Calendar event creation
- Slack notifications
- Email replies
- Advanced scheduling

---

## 🚀 **Next: Commit & Prepare Phase 4**

```bash
cd C:\Users\bhaga\Desktop\joshu
git add .
git commit -m "Phase 3: Add task approval UI and workflow"
git push

# Then: I'll write Phase 4 prompt
# Phase 4: Calendar + Notifications
```

---

**Expected Time**: ~25-30 minutes to complete this entire checklist

**When done**: Report results and we'll move to Phase 4! 🎯
