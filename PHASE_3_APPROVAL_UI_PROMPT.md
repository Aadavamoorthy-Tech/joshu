# Phase 3: Task Approval UI & Workflow - Detailed Prompt for Neon

**Status**: Ready to send to Neon  
**Estimated Build Time**: 3-4 hours  
**Current Project State**: Gmail polling working, tasks extracted from emails

---

## 📋 **Executive Summary**

Build the approval workflow UI so users can review extracted meeting tasks and decide which ones to keep. Users will see a clean interface showing meeting details (title, time, attendees, organizer) with approve/reject buttons. The backend will track approval status and prepare for Phase 4 integrations.

---

## 🎯 **What This Phase Builds**

### **User Experience**
1. User signs in via OAuth → sees Dashboard
2. Dashboard shows extracted meeting tasks from Gmail
3. Each task card displays:
   - Meeting title
   - Date & time
   - Organizer email
   - List of attendees
   - Meeting link (if available)
   - Current status (pending/approved/rejected)
4. User clicks "Approve" → task status changes to approved
5. User clicks "Reject" → task status changes to rejected + optional reason
6. Task status persists and updates immediately

### **Backend Workflow**
1. Existing `/tasks` endpoint already returns tasks
2. New endpoints to approve/reject tasks
3. Database tracks approval status and timestamp
4. No duplicate approvals allowed
5. Ready for Phase 4 (calendar sync, notifications)

---

## 🔧 **Backend Requirements**

### **Database Schema Updates**

Add to `tasks` table (migration or direct update):
```sql
ALTER TABLE tasks ADD COLUMN status VARCHAR(20) DEFAULT 'pending';  
-- Values: pending, approved, rejected

ALTER TABLE tasks ADD COLUMN approved_at TIMESTAMP NULL;
ALTER TABLE tasks ADD COLUMN rejected_at TIMESTAMP NULL;
ALTER TABLE tasks ADD COLUMN rejection_reason VARCHAR(500) NULL;
ALTER TABLE tasks ADD COLUMN approved_by_user BOOLEAN DEFAULT FALSE;
```

### **New API Endpoints**

**1. Approve a task**
```
POST /tasks/{task_id}/approve
Authorization: Bearer {token}
Response:
{
  "task_id": "uuid",
  "status": "approved",
  "approved_at": "2026-11-24T16:15:00Z",
  "message": "Task approved successfully"
}
```

**2. Reject a task**
```
POST /tasks/{task_id}/reject
Authorization: Bearer {token}
Body:
{
  "reason": "Already have this meeting scheduled"  // optional
}
Response:
{
  "task_id": "uuid",
  "status": "rejected",
  "rejected_at": "2026-11-24T16:15:00Z",
  "rejection_reason": "Already have this meeting scheduled",
  "message": "Task rejected successfully"
}
```

**3. Get single task (new endpoint)**
```
GET /tasks/{task_id}
Authorization: Bearer {token}
Response:
{
  "id": "uuid",
  "user_id": 1,
  "title": "Team Standup",
  "description": "Organizer: manager@company.com\nAttendees: you, colleague1, colleague2\nLink: https://meet.google.com/xxx",
  "scheduled_for": "2026-11-25T10:00:00Z",
  "source": "email",
  "status": "pending",  // pending, approved, rejected
  "organizer": "manager@company.com",
  "attendees": ["manager@company.com", "colleague1@company.com"],
  "calendar_event_link": "https://meet.google.com/xxx",
  "created_at": "2026-11-24T15:50:00Z",
  "approved_at": null,
  "rejected_at": null,
  "rejection_reason": null
}
```

**4. Get tasks with filters (update existing endpoint)**
```
GET /tasks?status=pending
GET /tasks?status=approved
GET /tasks?status=rejected
GET /tasks?status=all  (default: all)

Returns same task list but filtered by status
```

**5. Update task status directly (optional, for admin)**
```
PATCH /tasks/{task_id}
Authorization: Bearer {token}
Body:
{
  "status": "approved"  // or "rejected" or "pending"
}
```

### **Business Logic**

1. **Status Workflow**
   ```
   pending → approved (via POST /approve)
   pending → rejected (via POST /reject)
   approved → pending (via PATCH, optional rollback)
   rejected → pending (via PATCH, optional rollback)
   ```

2. **Idempotency**
   - If user approves same task twice → return success without error
   - Don't create duplicate approval records
   - Set `approved_at` only on first approval

3. **Timestamps**
   - `approved_at`: set when status changes to "approved"
   - `rejected_at`: set when status changes to "rejected"
   - Both set only once (don't update on subsequent calls)

4. **Validation**
   - Only authenticated users can approve/reject their own tasks
   - User_id must match the task's user_id
   - Return 403 Forbidden if user tries to approve someone else's task
   - Return 404 if task doesn't exist

5. **Error Handling**
   ```
   400 Bad Request: status is invalid
   401 Unauthorized: not authenticated
   403 Forbidden: not task owner
   404 Not Found: task doesn't exist
   500 Internal Server Error: database error
   ```

---

## 🎨 **Frontend Requirements**

### **UI Screens**

**1. Dashboard / Tasks List Screen**
```
┌─────────────────────────────────────────┐
│  📋 My Tasks                    👤 User │
├─────────────────────────────────────────┤
│  Filter: ○ All  ● Pending  ○ Approved   │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ 📅 Team Standup                     ││
│  │ Time: Tue, Nov 25, 2026 • 10:00 AM  ││
│  │ Organizer: manager@company.com      ││
│  │ Attendees: 3 people                 ││
│  │ Link: meet.google.com/xxx           ││
│  │                                      ││
│  │ [Approve] [Reject] [Details]        ││
│  └─────────────────────────────────────┘│
│                                         │
│  ┌─────────────────────────────────────┐│
│  │ 📅 Project Review Meeting           ││
│  │ Time: Wed, Nov 26, 2026 • 2:00 PM   ││
│  │ Organizer: team-lead@company.com    ││
│  │ Attendees: 5 people                 ││
│  │ Link: meet.google.com/yyy           ││
│  │                                      ││
│  │ [Approve] [Reject] [Details]        ││
│  └─────────────────────────────────────┘│
│                                         │
│  ✓ Approved (1)                         │
│  ✗ Rejected (0)                         │
│                                         │
└─────────────────────────────────────────┘
```

**2. Task Detail Modal (on [Details] click)**
```
┌──────────────────────────────────────────┐
│ ✕                                        │
├──────────────────────────────────────────┤
│ 📅 Team Standup                          │
│                                          │
│ When:                                    │
│ Tuesday, November 25, 2026               │
│ 10:00 AM - 10:30 AM                      │
│                                          │
│ Who:                                     │
│ Organizer: manager@company.com           │
│ Attendees:                               │
│   • colleague1@company.com               │
│   • colleague2@company.com               │
│   • you@yourcompany.com                  │
│                                          │
│ Meeting Link:                            │
│ https://meet.google.com/xxx [Open]       │
│                                          │
│ Description:                             │
│ [Full email body/description]            │
│                                          │
│ ┌────────────────────────────────────────┐
│ │ Reason for rejection (if rejected):    │
│ │ [text field or display reason]         │
│ └────────────────────────────────────────┘
│                                          │
│  [Approve] [Reject] [Close]              │
│                                          │
└──────────────────────────────────────────┘
```

**3. Reject Confirmation Dialog**
```
┌────────────────────────────────────────┐
│ Reject Task?                           │
├────────────────────────────────────────┤
│ Are you sure you want to reject this   │
│ task? You can still approve it later.  │
│                                        │
│ Optional: Why are you rejecting?       │
│ ┌────────────────────────────────────┐ │
│ │ [Already scheduled / Not relevant] │ │
│ │ [Free text input field]            │ │
│ └────────────────────────────────────┘ │
│                                        │
│            [Cancel] [Reject]           │
│                                        │
└────────────────────────────────────────┘
```

### **Components to Build**

1. **TaskListScreen / TasksPage**
   - Display tasks from `GET /tasks`
   - Filter buttons (All, Pending, Approved, Rejected)
   - Shows task count per status
   - Scroll/pagination if many tasks

2. **TaskCard Component**
   - Shows meeting title, time, organizer, attendees
   - Two buttons: "Approve", "Reject"
   - Optional "Details" button
   - Visual indicator for status (pending = light, approved = green, rejected = red)

3. **TaskDetailModal Component**
   - Full task details
   - Meeting link clickable
   - Approve/Reject buttons
   - If status is "approved/rejected", show that badge
   - If rejected, show rejection reason

4. **RejectConfirmationDialog Component**
   - Confirmation before rejecting
   - Optional text field for rejection reason
   - Cancel / Reject buttons

### **UI Behavior**

1. **On Approve Click**
   - POST `/tasks/{id}/approve`
   - Show loading spinner
   - On success → Task status badge changes to ✓ Approved (green)
   - Show toast: "Task approved!"
   - Move task to "Approved" section if filtering by status
   - Buttons become disabled or hide

2. **On Reject Click**
   - Show RejectConfirmationDialog
   - User can type optional reason
   - POST `/tasks/{id}/reject` with optional reason
   - Show loading spinner
   - On success → Task status badge changes to ✗ Rejected (red)
   - Show toast: "Task rejected"
   - Move task to "Rejected" section if filtering by status
   - Buttons become disabled or hide

3. **On Details Click**
   - Open TaskDetailModal
   - Show full task info
   - User can still approve/reject from modal
   - Close modal on confirmation

4. **Filtering**
   - All: shows all tasks
   - Pending: shows only status="pending"
   - Approved: shows only status="approved"
   - Rejected: shows only status="rejected"

5. **Empty State**
   - If no tasks: show "No tasks yet. Keep checking your email!"
   - If no pending tasks: show "All tasks reviewed! 🎉"

### **State Management**

Use Flutter's existing state management (likely GetX or Provider based on prior phases):
- Load tasks on screen mount
- Keep task list in memory
- Optimistic update on approve/reject (update UI immediately, then confirm with backend)
- If backend fails, revert to previous state and show error

---

## ✅ **Testing Checklist**

After implementation, Neon should verify:

**Backend Tests**
- [ ] `POST /tasks/{id}/approve` changes status to "approved"
- [ ] `POST /tasks/{id}/reject` changes status to "rejected"
- [ ] `POST /tasks/{id}/reject` with reason stores reason in DB
- [ ] `GET /tasks/{id}` returns approved_at and rejected_at timestamps
- [ ] Calling approve twice doesn't create duplicates (idempotent)
- [ ] Calling reject twice doesn't create duplicates (idempotent)
- [ ] `GET /tasks?status=pending` only returns pending tasks
- [ ] `GET /tasks?status=approved` only returns approved tasks
- [ ] `GET /tasks?status=rejected` only returns rejected tasks
- [ ] 403 Forbidden if user tries to approve another user's task
- [ ] 404 Not Found if task_id doesn't exist
- [ ] Timestamps are set correctly (created_at, approved_at, rejected_at)

**Frontend Tests**
- [ ] Tasks load on screen mount
- [ ] Clicking "Approve" calls POST /tasks/{id}/approve
- [ ] Clicking "Reject" shows confirmation dialog
- [ ] Confirming reject calls POST /tasks/{id}/reject
- [ ] Task status updates immediately (optimistic update)
- [ ] Task moves to "Approved" section after approval
- [ ] Task moves to "Rejected" section after rejection
- [ ] Filter buttons work correctly
- [ ] Details modal shows full task info
- [ ] Clicking meeting link opens in browser
- [ ] Toast messages appear on success
- [ ] Error messages appear on failure
- [ ] Rejection reason is captured and displayed

**Integration Tests**
- [ ] Sign in → See pending tasks
- [ ] Approve task → Status changes in DB
- [ ] Refresh page → Approved status persists
- [ ] Reject task with reason → Reason is stored
- [ ] Get rejected task → Reason is returned in API
- [ ] Multiple tasks can be approved/rejected independently
- [ ] No task appears twice after approval/rejection

---

## 📚 **Files to Modify/Create**

### **Backend (FastAPI)**

```
backend/
├── app/
│   ├── models/
│   │   └── task.py (UPDATE: add status, approved_at, rejected_at fields)
│   ├── routes/
│   │   ├── tasks.py (ADD: approve, reject endpoints)
│   │   └── existing endpoints (UPDATE: add status filtering)
│   └── database.py (UPDATE: migration or schema update)
└── tests/
    └── test_tasks_approval.py (NEW: test approve/reject logic)
```

### **Frontend (Flutter)**

```
app/lib/
├── screens/
│   ├── tasks_list_screen.dart (NEW or UPDATE)
│   └── task_detail_screen.dart (NEW or UPDATE)
├── widgets/
│   ├── task_card.dart (NEW)
│   ├── task_detail_modal.dart (NEW)
│   └── reject_confirmation_dialog.dart (NEW)
├── services/
│   ├── task_service.dart (UPDATE: add approve/reject methods)
│   └── existing services
└── models/
    └── task_model.dart (UPDATE: add status field)
```

---

## 🚀 **Implementation Steps for Neon**

**Step 1: Backend Database** (30 min)
- Create migration to add status, approved_at, rejected_at columns
- Or update existing tables if using simpler approach
- Ensure defaults are set (status = 'pending')

**Step 2: Backend API Endpoints** (1 hour)
- POST /tasks/{id}/approve
- POST /tasks/{id}/reject
- GET /tasks/{id}
- Update GET /tasks to filter by status
- Add validation and error handling

**Step 3: Frontend Models** (15 min)
- Update TaskModel to include status fields
- Add TaskStatus enum (pending, approved, rejected)

**Step 4: Frontend UI Components** (1.5 hours)
- Create TaskCard widget with Approve/Reject buttons
- Create TaskDetailModal widget
- Create RejectConfirmationDialog widget
- Create TasksListScreen with filtering

**Step 5: Frontend Business Logic** (45 min)
- Update TaskService with approve/reject methods
- Implement optimistic updates
- Add error handling and toast messages
- Add state management for task list

**Step 6: Testing** (1 hour)
- Test backend endpoints with Postman/curl
- Test frontend flows (approve, reject, filter)
- Verify data persists after refresh
- Check error cases

---

## 🔄 **Git Workflow**

1. Create feature branch: `git checkout -b feature/phase-3-approval-ui`
2. Commit backend changes: `git commit -m "Add task approval endpoints and status tracking"`
3. Commit frontend changes: `git commit -m "Build approval UI with task filtering and confirmation dialogs"`
4. Push: `git push -u origin feature/phase-3-approval-ui`
5. Create PR when ready

---

## 📝 **Notes**

- **Keep it simple**: Focus on approve/reject. Advanced features (workflows, permissions, notifications) are Phase 4.
- **Optimistic updates**: Update UI immediately, then confirm with backend for better UX
- **Error resilience**: If network fails, revert UI change and show error
- **Status persistence**: User should see status after page refresh
- **Phone-friendly**: Make sure buttons are easy to tap on mobile/desktop

---

## 🎯 **Success Criteria**

After Neon completes Phase 3:
- ✅ Users can view extracted meeting tasks
- ✅ Users can approve tasks with one click
- ✅ Users can reject tasks with optional reason
- ✅ Tasks show approval status (pending/approved/rejected)
- ✅ Status changes persist in database
- ✅ No duplicates if same task is approved twice
- ✅ All tasks can be filtered by status
- ✅ Full task details visible in modal
- ✅ Meeting links are clickable
- ✅ Toast messages confirm actions
- ✅ Error messages help users troubleshoot
- ✅ Works on desktop and mobile browsers

---

## 📞 **Communication Plan**

After Neon completes:
1. Pull changes into VS Code
2. Test locally with backend running
3. Verify all checklist items work
4. Commit and sync
5. Ready for Phase 4

**Estimated timeline**: 3-4 hours for Neon, 1 hour for testing

---

## 🔗 **Related Documents**

- Phase 1: OAuth foundation (completed)
- Phase 2: Gmail polling (completed)
- Phase 3: This document (approval UI)
- Phase 4: Integrations (calendar sync, notifications - coming next)

---

**Ready to send to Neon!** ✅
