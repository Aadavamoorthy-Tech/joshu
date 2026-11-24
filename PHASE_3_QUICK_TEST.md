# 🧪 Phase 3 Testing - Quick Start

**Status**: Phase 3 pulled, backend running, Flutter opening

---

## 🚀 **Quick Action (DO THIS NOW)**

VS Code is opening. Follow these steps:

### **Step 1: Open Command Palette**
```
Press: Ctrl+Shift+P
```

### **Step 2: Run Flutter Web**
```
Type: flutter run
Select: Flutter: Run Web
Press: Enter
```

### **Step 3: Wait for Compilation**
- Pub get: ~30 seconds
- Dart compilation: ~1-2 minutes
- Browser opens automatically

---

## 🌐 **What You'll See**

```
My Approval App
━━━━━━━━━━━━━━━━━━━━━━━━━
[Sign in with Google]

Backend Status: ✓ Connected
```

---

## 🔐 **Testing Steps**

### **1. Sign In (1-2 min)**
- Click: [Sign in with Google]
- Sign in with your Gmail
- Approve Gmail scope
- Dashboard loads

### **2. See Dashboard (Instant)**
You should see:
```
Filter: ○ All  ● Pending  ○ Approved  ○ Rejected

┌─────────────────────────────────────┐
│ 📅 Team Standup                     │
│ Time: Tue, Nov 25, 2026 • 10:00 AM  │
│ Organizer: manager@company.com      │
│ Attendees: 3 people                 │
│ Link: meet.google.com/xxx           │
│                                      │
│ [Approve] [Reject] [Details]        │
│ Status: pending                      │
└─────────────────────────────────────┘
```

### **3. Test Approve (1 min)**
- Click: [Approve] on any task
- Wait for loading
- **Expected**:
  - Toast: "Task approved!"
  - Status changes: "✓ Approved" (green)
  - Buttons disappear/disable

### **4. Test Reject (1 min)**
- Click: [Reject] on another task
- Dialog appears asking to confirm
- Optionally type reason
- Click [Reject]
- **Expected**:
  - Toast: "Task rejected"
  - Status changes: "✗ Rejected" (red)
  - Reason saved (if typed)

### **5. Test Filter (1 min)**
- Click: [Approved] - See only approved tasks
- Click: [Rejected] - See only rejected tasks
- Click: [Pending] - See only pending tasks
- Click: [All] - See all tasks

### **6. Test Persistence (1 min)**
- Approve/reject some tasks
- Refresh page (F5)
- Status should still show approved/rejected
- **If status is gone**: Something is wrong

---

## ✅ **Quick Checklist**

| Item | Expected | ✓ |
|------|----------|---|
| Dashboard loads | Shows tasks | ☐ |
| Can approve | Status → Approved | ☐ |
| Can reject | Status → Rejected | ☐ |
| Filter works | Shows correct tasks | ☐ |
| Persists | Status after refresh | ☐ |
| No errors | Console clean (F12) | ☐ |

---

## 🐛 **If Something Goes Wrong**

### **"Tasks not loading"**
- Check backend: `curl http://localhost:8000/health`
- Check console: Press F12
- Refresh page

### **"Approve not working"**
- Check console for errors (F12)
- Check backend logs
- Try approving via API

### **"Status not saved after refresh"**
- Check database: `SELECT * FROM tasks`
- Verify approved_at timestamp is set
- Check backend error logs

---

## 📸 **Document Results**

After testing, tell me:
1. **Number of tasks**: ?
2. **Number approved**: ?
3. **Number rejected**: ?
4. **Any errors**: (copy/paste)
5. **Performance**: (responsive? slow?)

---

## ✨ **What Phase 3 Adds**

✅ Users can see extracted meeting tasks  
✅ Users can approve which meetings to keep  
✅ Users can reject unwanted meetings  
✅ Status persists in database  
✅ Tasks can be filtered by status  

---

**Timeline**: ~15 minutes to complete all tests

**When done**: Report results and we'll move to Phase 4! 🎯
