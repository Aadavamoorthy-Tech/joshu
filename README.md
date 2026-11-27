# Joshu — Personal AI Chief of Staff

Joshu is an event-driven **Personal AI Chief of Staff** that connects to your Google Workspace account, continuously monitors and comprehends incoming Gmail messages, prepares structured actions (drafted replies, RSVP confirmations, Google Calendar events, and bill payments), and executes them either upon your explicit approval or automatically under user-configured autonomous guardrails.

---

## Table of Contents

1. [Core Capabilities](#core-capabilities)
2. [System Architecture](#system-architecture)
3. [Repository Structure](#repository-structure)
4. [Prerequisites](#prerequisites)
5. [Google Cloud Console & OAuth 2.0 Setup](#google-cloud-console--oauth-20-setup)
6. [Environment Configuration (`backend/.env`)](#environment-configuration-backendenv)
7. [Running the Application Locally](#running-the-application-locally)
   - [Option A: One-Click Windows Launcher (`start-backend.bat` / `start-servers.ps1`)](#option-a-one-click-windows-launcher-start-backendbat--start-serversps1)
   - [Option B: Manual Terminal Startup](#option-b-manual-terminal-startup)
8. [Using Joshu](#using-joshu)
   - [View Tasks & AI Email Triage](#view-tasks--ai-email-triage)
   - [Joshu Autonomous Agent & Chat History](#joshu-autonomous-agent--chat-history)
9. [REST API Reference](#rest-api-reference)
10. [Security & Governance Model](#security--governance-model)
11. [Testing & Verification](#testing--verification)
12. [Troubleshooting](#troubleshooting)

---

## Core Capabilities

### 1. Google OAuth 2.0 & Encrypted Credential Storage
- **Multi-User Onboarding**: Sign in with any Google account via OAuth 2.0 (`openid`, `email`, `profile`, `gmail.readonly`, `gmail.modify`, `gmail.send`, `calendar.events`).
- **Incremental Workspace Authorization**: Connect additional Google services (**Google Drive**, **Google Sheets**, **Google Docs**, **Google Contacts**, **Google Tasks**, **Google Meet**) on demand directly from the Agent tab.
- **At-Rest Encryption**: OAuth access tokens and refresh tokens are encrypted using **Fernet (AES-128-CBC + HMAC-SHA256)** before being stored in the database, with automatic token refresh prior to expiry.

### 2. Automated Gmail Polling & AI Email Comprehension
- **Background & On-Demand Sync**: A background daemon polls connected Gmail inboxes on a configurable schedule (`GMAIL_POLL_INTERVAL_MINUTES`) and deduplicates messages by Gmail Message ID.
- **ICS & Calendar Invitation Extraction**: Parses `text/calendar` MIME parts and `.ics` attachments to extract organizer, attendees, location, start/end timestamps, and meeting links.
- **AI Comprehension & Smart Triage**:
  - Analyzes each incoming email using **Google Gemini** (`gemini-2.5-flash` with automatic model fallback and <1ms deterministic triage fallback).
  - Classifies every message into one of five actionable categories:
    - `payment_request` — Extracts amount, currency (`INR`, `USD`, `EUR`, `GBP`), payee name, UPI ID (VPA), bank account number, IFSC code, and invoice reference.
    - `meeting_rsvp` — Prepares an RSVP confirmation email draft and extracts Google Calendar event details.
    - `meeting_invite` — Extracts event title, UTC start/end times, location, and attendees for one-click Google Calendar scheduling.
    - `reply_needed` — Drafts a context-aware, executive response ready for review or immediate sending.
    - `informational` — Summarizes security notices, receipts, and newsletters requiring no reply or payment.
- **Focused Task Cards**:
  - Each task card in **View Tasks** displays **only the AI-analyzed description** of what the email is about, junto with its category badge, status badge, recommended action prompt, and approval controls.
  - Clicking anywhere on a task card opens the detail modal containing the **original email subject, sender details, full email body**, and editable fields for the reply draft, calendar event, or payment parameters.

### 3. Real Action Execution & Inbox Cleanup
- **Gmail Reply & RSVP Sending**: Sends threaded replies (`In-Reply-To` / `References`) directly through the user's Gmail account.
- **Google Calendar Scheduling**: Creates real calendar events on the user's primary Google Calendar and attaches the event link to the task execution receipt.
- **Payment Execution**: Executes approved bill payments via **RazorpayX Live Payouts** (UPI VPA or IMPS/NEFT bank transfer), **Stripe PaymentIntents**, or a custom payment webhook, or records a verified payment authorization audit receipt.
- **Inbox Archiving**: Automatically marks processed emails as read (`UNREAD` removed) and moves them out of `INBOX` into the `Joshu/Processed` label upon approval or rejection.

### 4. Joshu Autonomous Agent Workspace
- **Gemini-Style Conversational Interface**:
  - Clean prompt stage (*"How can Agent help you today"*) with an *"Ask agent"* prompt bar, animated horizontal wave thinking indicator, and an inline stop-response square button.
  - Starts a fresh chat session each time you sign in, while preserving all previous conversations in the left sidebar under **Chat History** (visible only when the **Agent** tab is active).
- **Persistent Per-Chat History**:
  - Clicking **Clear Chat** clears only the active conversation stage to start a fresh chat while keeping all past conversations saved in **Chat History**.
  - Each chat history tile includes a 3-dots (`⋮`) menu that opens a floating popover with a **Delete chat** option to permanently remove a specific conversation.
- **Live Autonomous Rule Engine**:
  - Instruct the agent in plain language (e.g., *"Make all payments under 1000 Rs automatically without asking"*, *"Automatically archive all informational emails"*, *"Auto-schedule all calendar invites"*).
  - The agent updates your persistent `AgentPolicy`, rewrites the live Python policy module (`backend/app/services/agent_runtime_rules.py`), and immediately executes any matching pending tasks.
- **Full Application Control**:
  - Ask the agent to list pending tasks, approve or reject specific tasks by name or ID, send emails, schedule calendar meetings, sync your inbox, or connect additional Google Workspace services.

---

## System Architecture

```text
+-------------------------------------------------------------------------+
|                   Frontend UI (.open-design/auth.html)                  |
|   - View Tasks Workspace (AI-analyzed task cards + full email modal)    |
|   - Agent Workspace (Gemini-style chat + persistent Chat History)       |
+------------------------------------+------------------------------------+
                                     | REST API (Bearer Token / Cookie)
                                     v
+-------------------------------------------------------------------------+
|                    FastAPI Backend (backend/app/main.py)                |
|                                                                         |
|  +-------------------+  +--------------------+  +--------------------+  |
|  |   /auth Routes    |  |   /tasks Routes    |  |   /agent Routes    |  |
|  | - Google OAuth    |  | - List & Filter    |  | - Conversational   |  |
|  | - Token Refresh   |  | - AI Triage        |  |   Agent Controller |  |
|  | - Session Mgmt    |  | - Approve / Reject |  | - Autonomous Rules |  |
|  +---------+---------+  +---------+----------+  +---------+----------+  |
|            |                      |                       |             |
|            v                      v                       v             |
|  +-------------------------------------------------------------------+  |
|  |                        Service Layer                              |  |
|  | - gmail_poller.py         (Background scheduler & MIME/ICS parse) |  |
|  | - email_analyzer.py       (Gemini AI & instant triage engine)     |  |
|  | - google_actions.py       (Gmail send/archive & Calendar events)  |  |
|  | - payment_executor.py     (RazorpayX / Stripe / Webhook payouts)  |  |
|  | - agent_service.py        (Tool execution & policy enforcement)   |  |
|  | - agent_runtime_rules.py  (Live auto-generated policy guardrails) |  |
|  +---------------------------------+---------------------------------+  |
+------------------------------------|------------------------------------+
                                     v
+-------------------------------------------------------------------------+
|               Database Layer (SQLite locally / PostgreSQL)              |
|   Models: User, Session, GoogleOAuthToken, Task, AgentPolicy,           |
|           AgentChatMessage                                              |
+-------------------------------------------------------------------------+
```

---

## Repository Structure

```text
.
├── .open-design/
│   └── auth.html                          # Main web application UI (Tasks + Agent workspace)
├── backend/
│   ├── app/
│   │   ├── middleware/
│   │   │   └── auth.py                    # Session token validation & auth error helpers
│   │   ├── models/
│   │   │   ├── agent.py                   # AgentPolicy & AgentChatMessage SQLAlchemy models
│   │   │   ├── session.py                 # Session SQLAlchemy model
│   │   │   ├── task.py                    # Task & GoogleOAuthToken SQLAlchemy models
│   │   │   └── user.py                    # User SQLAlchemy model
│   │   ├── routes/
│   │   │   ├── agent.py                   # /agent/state, /agent/chat, /agent/policy, /agent/history
│   │   │   ├── auth.py                    # /auth/signin, /auth/callback, /auth/me, /auth/logout
│   │   │   └── tasks.py                   # /tasks, /tasks/sync, /tasks/{id}/approve, /tasks/{id}/reject
│   │   ├── services/
│   │   │   ├── agent_runtime_rules.py     # Live Python autonomous policy module written by Joshu Agent
│   │   │   ├── agent_service.py           # Conversational agent engine, tool router & policy executor
│   │   │   ├── email_analyzer.py          # Gemini AI email comprehension & deterministic triage
│   │   │   ├── gmail_poller.py            # Gmail API inbox poller & background APScheduler daemon
│   │   │   ├── google_actions.py          # Gmail reply sender, label archiver & Calendar event creator
│   │   │   ├── invite_parser.py           # RFC 5545 ICS calendar invite parser
│   │   │   └── payment_executor.py        # RazorpayX / Stripe / Webhook payment execution service
│   │   ├── config.py                      # Environment & settings loader
│   │   ├── database.py                    # SQLAlchemy engine & session factory
│   │   ├── encryption.py                  # Fernet symmetric encryption for OAuth tokens
│   │   └── main.py                        # FastAPI application entrypoint & CORS configuration
│   ├── tests/                             # Backend pytest unit & integration test suite
│   ├── .env.example                       # Template for backend/.env configuration
│   ├── main.py                            # Top-level Uvicorn entrypoint (`uvicorn main:app`)
│   ├── requirements.txt                   # Production Python dependencies
│   └── requirements-dev.txt               # Development & testing dependencies
├── preview_server/                        # Self-contained preview server modules for cloud/iframe preview
├── tests/                                 # End-to-end UI, OAuth, and polling verification tests
├── app.py                                 # Standalone preview server on port 3000
├── start-backend.bat                      # Windows batch launcher for frontend + backend servers
├── start-servers.ps1                      # PowerShell job-managed server launcher (ports 3000 & 8000)
├── restart.bat / restart.ps1              # Quick server restart scripts
└── README.md                              # Project documentation
```

---

## Prerequisites

- **Python**: Python 3.10 or newer
- **Google Cloud Project**: A project in [Google Cloud Console](https://console.cloud.google.com/) with the **Gmail API** and **Google Calendar API** enabled and an **OAuth 2.0 Web Client ID**
- **Gemini API Key** *(recommended)*: A Google AI Studio API key (`GEMINI_API_KEY`) for deep LLM email comprehension and conversational agent responses

---

## Google Cloud Console & OAuth 2.0 Setup

1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Navigate to **APIs & Services → Library** and enable:
   - **Gmail API**
   - **Google Calendar API**
3. Navigate to **APIs & Services → OAuth consent screen**:
   - Configure the app name (**Joshu**), support email, and scopes:
     - `openid`, `email`, `profile`
     - `https://www.googleapis.com/auth/gmail.readonly`
     - `https://www.googleapis.com/auth/gmail.modify`
     - `https://www.googleapis.com/auth/gmail.send`
     - `https://www.googleapis.com/auth/calendar.events`
   - If the consent screen is in **Testing** mode, add your Gmail address under **Test users**.
4. Navigate to **APIs & Services → Credentials → Create Credentials → OAuth client ID**:
   - Application type: **Web application**
   - **Authorized JavaScript origins**:
     - `http://localhost:3000`
     - `http://localhost:5000`
     - `http://localhost:8000`
   - **Authorized redirect URIs**:
     - `http://localhost:3000/auth.html`
     - `http://localhost:3000/auth/callback`
     - `http://localhost:5000/auth.html`
     - `http://localhost:8000/auth/callback`
5. Copy the **Client ID** and **Client Secret** into `backend/.env`.

---

## Environment Configuration (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and fill in your credentials:

```powershell
Copy-Item backend\.env.example backend\.env
```

Generate your `SECRET_KEY` and `ENCRYPTION_KEY` using Python:

```powershell
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(32))"
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
```

### Environment Variables Reference

| Variable | Required | Default | Description |
| :--- | :---: | :--- | :--- |
| `GOOGLE_CLIENT_ID` | **Yes** | — | Google OAuth 2.0 Web Client ID |
| `GOOGLE_CLIENT_SECRET` | **Yes** | — | Google OAuth 2.0 Web Client Secret |
| `GOOGLE_REDIRECT_URI` | **Yes** | `http://localhost:3000/auth.html` | OAuth redirect URI matching your frontend origin |
| `SECRET_KEY` | **Yes** | — | 32+ character secret used for session signing |
| `ENCRYPTION_KEY` | **Yes** | — | Base64 Fernet key used to encrypt OAuth tokens at rest |
| `GEMINI_API_KEY` | Recommended | — | Google Gemini API key for AI email triage & Agent chat |
| `GEMINI_MODEL` | No | `gemini-2.5-flash` | Gemini model name for email analysis and agent responses |
| `DATABASE_URL` | No | `sqlite:///./joshu.db` | SQLAlchemy database URL (SQLite locally or PostgreSQL in production) |
| `FRONTEND_URL` | No | `http://localhost:3000` | Primary frontend origin allowed by CORS |
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost:3000,http://localhost:5000` | Comma-separated list of allowed browser origins |
| `GMAIL_POLL_INTERVAL_MINUTES` | No | `15` | Background Gmail polling interval in minutes |
| `GMAIL_MAX_MESSAGES_PER_POLL` | No | `25` | Maximum messages fetched per inbox sync |
| `GMAIL_INCLUDE_GENERAL_EMAILS` | No | `true` | Analyze all inbox emails (`true`) or calendar invites only (`false`) |
| `GMAIL_PROCESSED_LABEL` | No | `Joshu/Processed` | Gmail label where approved/rejected emails are archived |
| `PAYMENT_PROVIDER` | No | `internal` | Payment execution provider (`razorpayx`, `stripe`, `webhook`, or `internal`) |

---

## Running the Application Locally

First, create the Python virtual environment in the repository root and install the backend dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements-dev.txt
```

### Option A: One-Click Windows Launcher (`start-backend.bat` / `start-servers.ps1`)

The repository includes a Windows Job Object launcher that starts both the frontend static server (default port `3000`) and the FastAPI backend server (default port `8000`) in a single window, verifies that neither port is already occupied, and automatically stops both processes when you press `Ctrl+C` or close the window.

Double-click **`start-backend.bat`** or run from PowerShell:

```powershell
.\start-backend.bat
```

You can also specify custom ports via `start-servers.ps1`:

```powershell
.\start-servers.ps1 -FrontendPort 3000 -BackendPort 8000
```

Then open **`http://localhost:3000`** in your browser.

### Option B: Manual Terminal Startup

**Terminal 1 — FastAPI Backend (Port 8000):**

```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Terminal 2 — Frontend UI (Port 3000):**

```powershell
.\.venv\Scripts\python.exe serve_frontend.py 3000
```

Open **`http://localhost:3000`** in your browser (and verify backend health at `http://localhost:8000/health`).

---

## Using Joshu

### View Tasks & AI Email Triage
1. Sign in with your Google account using **Sign In with Google**.
2. Joshu automatically polls your inbox and analyzes each email with AI.
3. In **View Tasks**, each task card displays **only the AI-analyzed description** of the email along with its category badge (`Payment Request`, `Meeting RSVP`, `Calendar Invite`, `Reply Needed`, or `Informational`), status badge (`pending`, `approved`, `rejected`), and quick action buttons.
4. **Click any task card** to open the full inspection modal containing:
   - The original email **Subject**, **Sender**, **Date/Schedule**, and **Full Original Email Content**.
   - Editable fields for the drafted reply, calendar event title/time/location, or payment payee/amount/UPI/bank details before executing.

### Joshu Autonomous Agent & Chat History
1. Switch to the **Agent** tab in the left sidebar.
2. Each new sign-in opens a fresh chat stage (*"How can Agent help you today"*) with an *"Ask agent"* prompt box.
3. While the agent is thinking, an animated horizontal wave indicator appears and the prompt button switches to a stop-response button.
4. **Persistent Chat History**:
   - Every conversation you have is automatically saved under **Chat History** in the left sidebar (visible only while on the **Agent** tab).
   - Clicking **Clear Chat** in the top-right corner clears only the active screen so you can start a new topic—your previous conversations remain stored in **Chat History**.
   - To permanently delete a conversation from history, click the 3-dots (`⋮`) button on the right edge of that chat history tile and select **Delete chat** from the floating popover menu.

---

## REST API Reference

### Health & Authentication
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/health` | Returns backend service health and UTC timestamp |
| `POST` | `/auth/signin` | Generates a Google OAuth 2.0 authorization URL with CSRF state |
| `GET` | `/auth/callback` | Exchanges Google OAuth `code` & `state` for an encrypted token record and session |
| `GET` | `/auth/me` | Returns authenticated user profile and granted Google OAuth capability flags |
| `POST` | `/auth/logout` | Invalidates the current session token and clears the session cookie |

### Tasks & Inbox Actions
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/tasks` | Lists tasks for the authenticated user (`status=all\|pending\|approved\|rejected`) |
| `POST` | `/tasks/sync` | Triggers an immediate Gmail inbox poll and AI analysis run |
| `GET` | `/tasks/sync/status` | Returns Gmail connection health, granted scopes, and last sync timestamp |
| `POST` | `/tasks/analyze-pending` | Runs Gemini AI comprehension across pending tasks |
| `GET` | `/tasks/{task_id}` | Returns full details for a single task owned by the user |
| `POST` | `/tasks/{task_id}/approve` | Approves a task and executes reply, RSVP, Calendar event, payment, and archive |
| `POST` | `/tasks/{task_id}/reject` | Rejects a task and archives the email into `Joshu/Processed` |

### Autonomous Agent & Chat History
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/agent/state` | Returns current autonomous policy, Google Workspace service connections, and chat history |
| `POST` | `/agent/chat` | Sends a prompt to Joshu Agent (`message`, `chat_id`) and executes any requested tools/rules |
| `PATCH` | `/agent/policy` | Toggles autonomous rules (`auto_pay_enabled`, `auto_pay_max_amount`, `auto_archive_informational`, `auto_add_calendar_invites`, `auto_send_replies`) |
| `DELETE` | `/agent/history` | Deletes a specific chat session (`?chat_id=...&message_id=...`) from persistent history |

---

## Security & Governance Model

- **Backend-Enforced Guardrails**: Autonomous payment limits (`should_auto_execute_payment`), inbox archiving rules, and calendar/reply policies are enforced deterministically in Python (`backend/app/services/agent_runtime_rules.py` and `agent_service.py`), never delegated solely to LLM prompts.
- **Prompt-Injection Defense**: Untrusted email bodies are isolated inside `<UNTRUSTED_EMAIL>` tags with strict system instructions prohibiting the model from following embedded commands, altering recipients, or inventing payment requests.
- **Strict Multi-Tenant Isolation**: Every database query for tasks, OAuth tokens, policies, and chat history is scoped strictly to `current_session.user_id`.
- **Idempotent Execution**: Approving an already-approved task returns the existing execution receipt without double-charging payments, double-sending emails, or duplicating calendar events.

---

## Testing & Verification

Run the backend unit and integration test suite with `pytest`:

```powershell
.\.venv\Scripts\python.exe -m pytest -q backend\tests
```

Run the preview server and UI verification test suite with `unittest`:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

---

## Troubleshooting

- **"Port(s) 3000, 8000 already in use" when running `start-backend.bat`**:
  Stop existing Python/Uvicorn processes (`restart.bat` or `Stop-Process -Name python`) or pass custom ports to `.\start-servers.ps1 -FrontendPort 3001 -BackendPort 8001`.
- **`redirect_uri_mismatch` on Google Sign-In**:
  Ensure the exact origin and callback URL shown in your browser address bar (e.g., `http://localhost:3000/auth.html`) is listed under **Authorized redirect URIs** in Google Cloud Console and matches `GOOGLE_REDIRECT_URI` in `backend/.env`.
- **`403 access_denied` on Google Sign-In**:
  If your Google Cloud OAuth consent screen is in **Testing** mode, add your Gmail address under **APIs & Services → OAuth consent screen → Test users**.
