"""Zero-dependency Python preview server for Joshu (Personal AI Chief of Staff).

Runs inside the preview environment on PORT (default 3000) using only the Python
standard library plus the real Phase 2 `invite_parser` module from `backend/`.
For full OAuth + Gmail API execution, run `backend/` (FastAPI) and `app/` (Flutter).
"""

from __future__ import annotations

import base64
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import parse_qs, urlparse

# Import the real Phase 2 Gmail/ICS invitation parser from backend/.
BACKEND_DIR = Path(__file__).resolve().parent / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.invite_parser import parse_gmail_invite_message  # noqa: E402


def _iso_utc(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _seed_tasks() -> List[Dict[str, Any]]:
    """Seed realistic meeting invitations parsed through the real Phase 2 ICS parser."""
    now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
    samples = [
        (
            "demo-msg-1",
            "Q4 Board Strategy Review",
            "sarah.chen@acme.com",
            ["sarah.chen@acme.com", "cfo@acme.com", "founder@joshu.app"],
            now + timedelta(days=1, hours=2),
            "https://calendar.google.com/calendar/event?eid=q4-board-review",
            "Quarterly revenue forecast, hiring plan, and Series A roadmap.",
        ),
        (
            "demo-msg-2",
            "Enterprise Customer Onboarding — Northstar",
            "partnerships@northstar.io",
            ["partnerships@northstar.io", "cs-lead@joshu.app", "founder@joshu.app"],
            now + timedelta(days=2, hours=4),
            "https://meet.google.com/nst-exec-sync",
            "Kickoff call to finalize SSO configuration and workspace provisioning.",
        ),
        (
            "demo-msg-3",
            "Weekly Engineering & Product Sync",
            "eng-lead@joshu.app",
            ["eng-lead@joshu.app", "design@joshu.app", "founder@joshu.app"],
            now + timedelta(days=3, hours=1),
            "https://meet.google.com/eng-weekly-sync",
            "Phase 3 approval workflow QA and Phase 4 Google Calendar writeback scope.",
        ),
    ]

    seeded: List[Dict[str, Any]] = []
    for msg_id, summary, organizer, attendees, start_dt, link, notes in samples:
        end_dt = start_dt + timedelta(minutes=45)
        ics_lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "BEGIN:VEVENT",
            f"UID:{msg_id}@joshu.app",
            f"SUMMARY:{summary}",
            f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%SZ')}",
            f"ORGANIZER:mailto:{organizer}",
            *[f"ATTENDEE:mailto:{a}" for a in attendees],
            f"URL:{link}",
            f"DESCRIPTION:{notes}",
            "END:VEVENT",
            "END:VCALENDAR",
        ]
        parsed = parse_gmail_invite_message(
            {
                "id": msg_id,
                "threadId": f"thr-{msg_id}",
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": f"Invitation: {summary}"},
                        {"name": "From", "value": organizer},
                    ],
                    "parts": [
                        {
                            "mimeType": "text/calendar",
                            "filename": "invite.ics",
                            "body": {"data": _b64url("\r\n".join(ics_lines))},
                        }
                    ],
                },
            }
        )
        if parsed is not None:
            seeded.append(
                {
                    "id": str(uuid.uuid4()),
                    "title": parsed.title,
                    "description": parsed.description,
                    "scheduled_for": _iso_utc(parsed.scheduled_for),
                    "source": parsed.source,
                    "status": "pending",
                    "organizer": parsed.organizer,
                    "attendees": parsed.attendees,
                    "calendar_event_link": parsed.calendar_event_link,
                    "raw_data": parsed.raw_data,
                    "created_at": _iso_utc(now),
                    "updated_at": _iso_utc(now),
                    "approved_at": None,
                    "rejected_at": None,
                    "rejection_reason": None,
                    "approved_by_user": False,
                }
            )
    return seeded


TASKS_STORE: List[Dict[str, Any]] = _seed_tasks()

PREVIEW_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Joshu — Personal AI Chief of Staff</title>
  <style>
    :root {
      --bg: #f8fafc;
      --surface: #ffffff;
      --border: #e2e8f0;
      --text: #0f172a;
      --muted: #475569;
      --primary: #1e3a8a;
      --primary-soft: #eff6ff;
      --approve: #15803d;
      --approve-bg: #f0fdf4;
      --approve-border: #bbf7d0;
      --reject: #b91c1c;
      --reject-bg: #fef2f2;
      --reject-border: #fecaca;
      --pending-bg: #fef3c7;
      --pending-fg: #92400e;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.5;
    }
    header {
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .header-inner {
      max-width: 920px;
      margin: 0 auto;
      padding: 14px 20px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      flex-wrap: wrap;
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .brand-mark {
      width: 34px;
      height: 34px;
      border-radius: 9px;
      background: var(--primary);
      color: #fff;
      display: grid;
      place-items: center;
      font-weight: 700;
      font-size: 16px;
    }
    .brand h1 { margin: 0; font-size: 17px; letter-spacing: -0.01em; }
    .brand span { font-size: 12px; color: var(--muted); display: block; }
    main {
      max-width: 920px;
      margin: 0 auto;
      padding: 24px 20px 56px;
    }
    .filters {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-bottom: 18px;
    }
    .chip {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      padding: 7px 14px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .chip.active {
      background: var(--primary);
      border-color: var(--primary);
      color: #fff;
    }
    .btn {
      border: 1px solid var(--border);
      background: var(--surface);
      color: var(--text);
      padding: 8px 14px;
      border-radius: 9px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
    }
    .btn:disabled { opacity: 0.5; cursor: not-allowed; }
    .btn-primary { background: var(--primary); border-color: var(--primary); color: #fff; }
    .btn-approve { background: var(--approve); border-color: var(--approve); color: #fff; }
    .btn-reject { background: transparent; border-color: var(--reject); color: var(--reject); }
    .card {
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 18px 20px;
      margin-bottom: 14px;
    }
    .card.approved { background: var(--approve-bg); border-color: var(--approve-border); }
    .card.rejected { background: var(--reject-bg); border-color: var(--reject-border); }
    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      gap: 12px;
    }
    .card-title { margin: 0; font-size: 16px; font-weight: 650; }
    .card-time { font-size: 13px; color: var(--muted); margin-top: 3px; }
    .badge {
      padding: 4px 10px;
      border-radius: 7px;
      font-size: 12px;
      font-weight: 700;
      text-transform: capitalize;
      white-space: nowrap;
    }
    .badge.pending { background: var(--pending-bg); color: var(--pending-fg); }
    .badge.approved { background: #dcfce7; color: #166534; }
    .badge.rejected { background: #fee2e2; color: #991b1b; }
    .meta {
      display: flex;
      gap: 16px;
      flex-wrap: wrap;
      margin: 12px 0;
      font-size: 13px;
      color: var(--muted);
    }
    .meta a { color: var(--primary); font-weight: 500; }
    .reason-box {
      margin: 10px 0;
      padding: 8px 12px;
      border-radius: 8px;
      background: #fee2e2;
      color: #991b1b;
      font-size: 13px;
    }
    .card-actions {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      align-items: center;
      padding-top: 12px;
      border-top: 1px solid var(--border);
    }
    .empty {
      background: var(--surface);
      border: 1px dashed var(--border);
      border-radius: 14px;
      padding: 42px 24px;
      text-align: center;
      color: var(--muted);
    }
    .toast {
      position: fixed;
      bottom: 20px;
      right: 20px;
      background: #0f172a;
      color: #fff;
      padding: 11px 16px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      box-shadow: 0 10px 25px rgba(15, 23, 42, 0.2);
      display: none;
    }
    .modal-backdrop {
      position: fixed;
      inset: 0;
      background: rgba(15, 23, 42, 0.45);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 16px;
      z-index: 30;
    }
    .modal {
      background: var(--surface);
      border-radius: 16px;
      max-width: 520px;
      width: 100%;
      padding: 22px 24px;
      box-shadow: 0 20px 45px rgba(15, 23, 42, 0.25);
    }
    .modal h2 { margin: 0 0 10px; font-size: 18px; }
    .modal textarea {
      width: 100%;
      min-height: 80px;
      padding: 10px;
      border: 1px solid var(--border);
      border-radius: 9px;
      font-family: inherit;
      font-size: 13px;
      margin: 10px 0 14px;
    }
    .modal-footer {
      display: flex;
      justify-content: flex-end;
      gap: 10px;
      margin-top: 14px;
    }
  </style>
</head>
<body>
  <header>
    <div class="header-inner">
      <div class="brand">
        <div class="brand-mark">J</div>
        <div>
          <h1>Joshu</h1>
          <span>Personal AI Chief of Staff — Approval Inbox</span>
        </div>
      </div>
      <div style="display:flex;gap:8px;align-items:center;">
        <button class="btn btn-primary" id="sync-btn">Sync Sample Invite</button>
      </div>
    </div>
  </header>

  <main>
    <div class="filters" id="filters"></div>
    <div id="task-list"></div>
  </main>

  <div class="modal-backdrop" id="reject-modal">
    <div class="modal">
      <h2>Reject Task?</h2>
      <p id="reject-modal-copy" style="color:var(--muted);font-size:14px;margin:0 0 10px;"></p>
      <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
        <button class="chip" type="button" data-quick="Already scheduled">Already scheduled</button>
        <button class="chip" type="button" data-quick="Not relevant">Not relevant</button>
        <button class="chip" type="button" data-quick="Declined elsewhere">Declined elsewhere</button>
      </div>
      <textarea id="reject-reason" maxlength="500" placeholder="Optional reason for rejecting..."></textarea>
      <div class="modal-footer">
        <button class="btn" id="reject-cancel">Cancel</button>
        <button class="btn btn-reject" id="reject-confirm" style="background:var(--reject);color:#fff;">Reject</button>
      </div>
    </div>
  </div>

  <div class="modal-backdrop" id="detail-modal">
    <div class="modal">
      <h2 id="detail-title"></h2>
      <div id="detail-body" style="font-size:14px;color:var(--muted);"></div>
      <div class="modal-footer">
        <button class="btn" id="detail-close">Close</button>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>

  <script>
    let allTasks = [];
    let activeFilter = "all";
    let pendingRejectId = null;

    function showToast(message) {
      const el = document.getElementById("toast");
      el.textContent = message;
      el.style.display = "block";
      clearTimeout(window.__toastTimer);
      window.__toastTimer = setTimeout(() => { el.style.display = "none"; }, 2600);
    }

    function formatDate(iso) {
      if (!iso) return "Time not specified";
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toLocaleString(undefined, {
        weekday: "short", month: "short", day: "numeric", year: "numeric",
        hour: "numeric", minute: "2-digit"
      });
    }

    function counts() {
      const c = { all: allTasks.length, pending: 0, approved: 0, rejected: 0 };
      for (const t of allTasks) {
        if (c[t.status] !== undefined) c[t.status]++;
      }
      return c;
    }

    function renderFilters() {
      const c = counts();
      const container = document.getElementById("filters");
      container.replaceChildren();
      for (const key of ["all", "pending", "approved", "rejected"]) {
        const btn = document.createElement("button");
        btn.className = "chip" + (activeFilter === key ? " active" : "");
        btn.textContent = key[0].toUpperCase() + key.slice(1) + " (" + c[key] + ")";
        btn.onclick = () => { activeFilter = key; render(); };
        container.appendChild(btn);
      }
    }

    function renderTasks() {
      const list = document.getElementById("task-list");
      list.replaceChildren();
      const filtered = activeFilter === "all"
        ? allTasks
        : allTasks.filter((t) => t.status === activeFilter);

      if (filtered.length === 0) {
        const empty = document.createElement("div");
        empty.className = "empty";
        empty.textContent = activeFilter === "pending" && allTasks.length > 0
          ? "All tasks reviewed!"
          : "No tasks in this view.";
        list.appendChild(empty);
        return;
      }

      for (const task of filtered) {
        const card = document.createElement("article");
        card.className = "card " + task.status;

        const top = document.createElement("div");
        top.className = "card-top";
        const left = document.createElement("div");
        const title = document.createElement("h3");
        title.className = "card-title";
        title.textContent = task.title;
        const time = document.createElement("div");
        time.className = "card-time";
        time.textContent = formatDate(task.scheduled_for);
        left.append(title, time);

        const badge = document.createElement("span");
        badge.className = "badge " + task.status;
        badge.textContent = task.status;
        top.append(left, badge);
        card.appendChild(top);

        const meta = document.createElement("div");
        meta.className = "meta";
        if (task.organizer) {
          const org = document.createElement("span");
          org.textContent = "Organizer: " + task.organizer;
          meta.appendChild(org);
        }
        if (Array.isArray(task.attendees) && task.attendees.length > 0) {
          const att = document.createElement("span");
          att.textContent = task.attendees.length + " attendees";
          meta.appendChild(att);
        }
        if (task.calendar_event_link && task.calendar_event_link.startsWith("https://")) {
          const a = document.createElement("a");
          a.href = task.calendar_event_link;
          a.target = "_blank";
          a.rel = "noopener noreferrer";
          a.textContent = "Meeting link";
          meta.appendChild(a);
        }
        card.appendChild(meta);

        if (task.status === "rejected" && task.rejection_reason) {
          const reason = document.createElement("div");
          reason.className = "reason-box";
          reason.textContent = "Rejection reason: " + task.rejection_reason;
          card.appendChild(reason);
        }

        const actions = document.createElement("div");
        actions.className = "card-actions";
        if (task.status === "pending") {
          const approveBtn = document.createElement("button");
          approveBtn.className = "btn btn-approve";
          approveBtn.textContent = "Approve";
          approveBtn.onclick = () => approveTask(task.id);

          const rejectBtn = document.createElement("button");
          rejectBtn.className = "btn btn-reject";
          rejectBtn.textContent = "Reject";
          rejectBtn.onclick = () => openRejectModal(task);

          actions.append(approveBtn, rejectBtn);
        }
        const detailsBtn = document.createElement("button");
        detailsBtn.className = "btn";
        detailsBtn.textContent = "Details";
        detailsBtn.onclick = () => openDetailModal(task);
        actions.appendChild(detailsBtn);

        card.appendChild(actions);
        list.appendChild(card);
      }
    }

    function render() {
      renderFilters();
      renderTasks();
    }

    async function loadTasks() {
      const res = await fetch("/tasks");
      const data = await res.json();
      allTasks = data.tasks || [];
      render();
    }

    async function approveTask(id) {
      const res = await fetch("/tasks/" + encodeURIComponent(id) + "/approve", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        allTasks = allTasks.map((t) => (t.id === id ? data.task : t));
        render();
        showToast("Task approved!");
      }
    }

    function openRejectModal(task) {
      pendingRejectId = task.id;
      document.getElementById("reject-modal-copy").textContent =
        'Confirm rejection for "' + task.title + '".';
      document.getElementById("reject-reason").value = "";
      document.getElementById("reject-modal").style.display = "flex";
    }

    function openDetailModal(task) {
      document.getElementById("detail-title").textContent = task.title;
      const body = document.getElementById("detail-body");
      body.replaceChildren();

      const rows = [
        ["When", formatDate(task.scheduled_for)],
        ["Status", task.status],
        ["Organizer", task.organizer || "Unknown"],
        ["Attendees", (task.attendees || []).join(", ") || "None"],
        ["Notes", task.description || "No description"]
      ];
      for (const [label, value] of rows) {
        const p = document.createElement("p");
        p.style.margin = "8px 0";
        const strong = document.createElement("strong");
        strong.style.color = "var(--text)";
        strong.textContent = label + ": ";
        p.append(strong, document.createTextNode(value));
        body.appendChild(p);
      }
      document.getElementById("detail-modal").style.display = "flex";
    }

    document.querySelectorAll("[data-quick]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.getElementById("reject-reason").value = btn.getAttribute("data-quick");
      });
    });

    document.getElementById("reject-cancel").onclick = () => {
      pendingRejectId = null;
      document.getElementById("reject-modal").style.display = "none";
    };

    document.getElementById("reject-confirm").onclick = async () => {
      if (!pendingRejectId) return;
      const id = pendingRejectId;
      const reason = document.getElementById("reject-reason").value.trim();
      document.getElementById("reject-modal").style.display = "none";
      pendingRejectId = null;

      const res = await fetch("/tasks/" + encodeURIComponent(id) + "/reject", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: reason || null })
      });
      if (res.ok) {
        const data = await res.json();
        allTasks = allTasks.map((t) => (t.id === id ? data.task : t));
        render();
        showToast("Task rejected");
      }
    };

    document.getElementById("detail-close").onclick = () => {
      document.getElementById("detail-modal").style.display = "none";
    };

    document.getElementById("sync-btn").onclick = async () => {
      const res = await fetch("/tasks/sync", { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        await loadTasks();
        showToast("Synced " + data.created_tasks + " new calendar invite");
      }
    };

    loadTasks();
  </script>
</body>
</html>
"""


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        return

    def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(min(length, 65536))
        try:
            parsed = json.loads(raw.decode("utf-8"))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/":
            data = PREVIEW_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        if path == "/health":
            self._send_json(200, {"status": "ok"})
            return

        if path == "/tasks":
            qs = parse_qs(parsed.query)
            status_filter = (qs.get("status", ["all"])[0] or "all").lower()
            items = (
                TASKS_STORE
                if status_filter == "all"
                else [t for t in TASKS_STORE if t["status"] == status_filter]
            )
            self._send_json(200, {"tasks": items, "total": len(items)})
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found", "status": 404})

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/tasks/sync":
            now = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)
            start_dt = now + timedelta(days=4, hours=3)
            end_dt = start_dt + timedelta(minutes=30)
            uid = uuid.uuid4().hex[:8]
            ics = "\r\n".join(
                [
                    "BEGIN:VCALENDAR",
                    "BEGIN:VEVENT",
                    f"UID:sync-{uid}@joshu.app",
                    f"SUMMARY:Vendor Contract Review #{len(TASKS_STORE) + 1}",
                    f"DTSTART:{start_dt.strftime('%Y%m%dT%H%M%SZ')}",
                    f"DTEND:{end_dt.strftime('%Y%m%dT%H%M%SZ')}",
                    "ORGANIZER:mailto:legal@partner.io",
                    "ATTENDEE:mailto:legal@partner.io",
                    "ATTENDEE:mailto:founder@joshu.app",
                    "URL:https://calendar.google.com/calendar/event?eid=vendor-review",
                    "DESCRIPTION:Final review of enterprise MSA terms.",
                    "END:VEVENT",
                    "END:VCALENDAR",
                ]
            )
            extracted = parse_gmail_invite_message(
                {
                    "id": f"sync-{uid}",
                    "threadId": f"thr-{uid}",
                    "payload": {
                        "headers": [{"name": "Subject", "value": "Invitation: Vendor Contract Review"}],
                        "parts": [
                            {
                                "mimeType": "text/calendar",
                                "filename": "invite.ics",
                                "body": {"data": _b64url(ics)},
                            }
                        ],
                    },
                }
            )
            created = 0
            if extracted is not None:
                TASKS_STORE.insert(
                    0,
                    {
                        "id": str(uuid.uuid4()),
                        "title": extracted.title,
                        "description": extracted.description,
                        "scheduled_for": _iso_utc(extracted.scheduled_for),
                        "source": extracted.source,
                        "status": "pending",
                        "organizer": extracted.organizer,
                        "attendees": extracted.attendees,
                        "calendar_event_link": extracted.calendar_event_link,
                        "raw_data": extracted.raw_data,
                        "created_at": _iso_utc(now),
                        "updated_at": _iso_utc(now),
                        "approved_at": None,
                        "rejected_at": None,
                        "rejection_reason": None,
                        "approved_by_user": False,
                    },
                )
                created = 1
            self._send_json(200, {"status": "completed", "created_tasks": created})
            return

        parts = [p for p in path.split("/") if p]
        if len(parts) == 3 and parts[0] == "tasks" and parts[2] in ("approve", "reject"):
            task_id, action = parts[1], parts[2]
            task = next((t for t in TASKS_STORE if t["id"] == task_id), None)
            if task is None:
                self._send_json(404, {"error": "task_not_found", "message": "Task not found", "status": 404})
                return

            now_iso = _iso_utc(datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0))
            if action == "approve":
                if task["status"] != "approved":
                    task["status"] = "approved"
                    task["approved_by_user"] = True
                    task["approved_at"] = task["approved_at"] or now_iso
                    task["updated_at"] = now_iso
                self._send_json(
                    200,
                    {
                        "task_id": task["id"],
                        "status": "approved",
                        "approved_at": task["approved_at"],
                        "task": task,
                        "message": "Task approved successfully",
                    },
                )
                return

            body = self._read_json_body()
            reason = str(body.get("reason") or "").strip()[:500] or None
            if task["status"] != "rejected":
                task["status"] = "rejected"
                task["approved_by_user"] = False
                task["rejected_at"] = task["rejected_at"] or now_iso
                task["rejection_reason"] = reason
                task["updated_at"] = now_iso
            self._send_json(
                200,
                {
                    "task_id": task["id"],
                    "status": "rejected",
                    "rejected_at": task["rejected_at"],
                    "rejection_reason": task["rejection_reason"],
                    "task": task,
                    "message": "Task rejected successfully",
                },
            )
            return

        self._send_json(404, {"error": "not_found", "message": "Route not found", "status": 404})


def main() -> None:
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "3000"))
    server = ThreadingHTTPServer((host, port), PreviewHandler)
    print(f"Joshu preview server listening on http://{host}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
