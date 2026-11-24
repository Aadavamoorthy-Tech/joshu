# Quick Start Guide - Personal AI Chief of Staff

## 🚀 TL;DR - What's Ready?

✅ **Backend (Python/FastAPI)**
- Health endpoint working
- OAuth endpoints stubbed and ready for implementation
- Credentials loaded from `.env`
- Ready to deploy on Render

✅ **Frontend (Flutter)**
- Architecture complete: Session, HTTP client, Riverpod state management
- Multi-platform ready: Web ✅, Android 📋, Windows 📋
- Web builds successfully
- Sign-in flow placeholder ready for OAuth wiring

---

## 🔧 Development Setup

### 1. Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements-dev.txt

# Create .env with Google OAuth credentials:
# GOOGLE_CLIENT_ID=xxx.apps.googleusercontent.com
# GOOGLE_CLIENT_SECRET=yyy

uvicorn main:app --reload
# Server running at http://localhost:8000
# Health check: GET http://localhost:8000/health → {"status":"ok"}
```

### 2. Frontend (Web)
```bash
cd app
flutter pub get
flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000
# OR
flutter build web --release  # outputs to build/web
```

---

## 📂 Key Files to Know

| File | Purpose | Next Action |
|------|---------|------------|
| `app/lib/main.dart` | App root with Riverpod | Wire OAuth sign-in screen |
| `app/lib/core/auth/session_service.dart` | Session lifecycle | Test with backend /oauth/token |
| `app/lib/core/network/api_client.dart` | HTTP + Bearer token | Test with real API calls |
| `app/lib/providers/auth_provider.dart` | Riverpod auth state | Build sign-in and inbox screens |
| `backend/main.py` | FastAPI server | Implement /oauth/authorize, /oauth/callback |
| `backend/.env` | Google OAuth credentials | Keep this secret! |

---

## 🔄 Architecture Quick Ref

### Session Flow
```
App Start
  ↓
SessionService.restoreSession()
  ├─ Checks secure storage for session token
  └─ Returns null if missing/expired
  ↓
If null → AuthStatus.signedOut → Show sign-in screen
If valid → AuthStatus.signedIn → Show inbox with tasks
```

### API Call Flow
```
Flutter UI
  ↓
apiClient.postJson("/tasks/approve", body: {...})
  ├─ ApiClient._send()
  │   ├─ Get token from SessionService
  │   ├─ Add Authorization: Bearer {token}
  │   ├─ Send HTTP request
  │   └─ Handle response
  │
  ├─ If 200/201 → Return JSON
  ├─ If 401 & !isRetry → Single-flight refresh → Retry
  ├─ If 403 googleReconnectNeeded → Callback → Show banner
  └─ If error → Throw ApiException
```

---

## 🎯 Immediate TODOs (Priority Order)

### 1. **Connect OAuth Endpoints** (1-2 hours)
- [ ] Wire `SignInScreen` to open `GET /oauth/authorize?...`
- [ ] Implement FastAPI OAuth code exchange
- [ ] Test session token returned and stored locally
- [ ] Test session restore on app restart

### 2. **Implement Gmail Polling** (2-3 hours)
- [ ] Create background worker on Render (APScheduler)
- [ ] Load user's Google token and call Gmail API
- [ ] Parse meeting invites → extract date, organizer, attendees
- [ ] Store tasks in DB with status=pending

### 3. **Build Approval UI** (2-3 hours)
- [ ] Create `ApprovalCard` widget with task details
- [ ] Add Approve/Reject buttons with state machine
- [ ] Show loading + error states
- [ ] Wire to `POST /tasks/{id}/approve` endpoint

### 4. **Connect to Calendar** (1-2 hours)
- [ ] On approve: Call Google Calendar API to create event
- [ ] Log to audit table
- [ ] Handle Idempotency-Key for retries

### 5. **Deploy to Render** (30 min)
- [ ] Set environment variables: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`
- [ ] Configure CORS origins
- [ ] Test OAuth flow end-to-end

---

## 🐛 Common Issues & Fixes

### "Session token is null"
→ User not signed in yet. Check `SessionService.restoreSession()` returns null initially.

### "401 Unauthorized from /tasks"
→ Check Bearer token is being sent. See `ApiClient._send()` adding Authorization header.

### "Web build fails: flutter_secure_storage not found"
→ **Fixed!** Conditional imports + NativeSecureStorageAdapter stub in token_storage_web.dart handle this.

### "Google token expired after 7 days"
→ Expected in Testing mode. Backend should return 403 with `code: "googleReconnectNeeded"`.
→ Flutter shows ReconnectGoogleBanner and updates AuthState.googleReconnectRequired.

### "CORS error on web"
→ FastAPI needs CORS headers for: Authorization, Content-Type, Idempotency-Key.
→ Check `main.py` CORSMiddleware configuration.

---

## 🧪 Testing Quick Commands

```bash
# Backend health check
curl http://localhost:8000/health

# Backend tests
cd backend
pytest tests/

# Flutter web build
cd app
flutter build web --no-wasm-dry-run

# Flutter analyze (platform-specific warnings expected)
flutter analyze

# Flutter widget tests
flutter test test/widget_test.dart
```

---

## 📋 Session vs. Google Token Management

| Concept | Stored | Lifetime | Use Case |
|---------|--------|----------|----------|
| **Session Token** | Secure storage (Keystore/localStorage) | 30 days | Authenticate with FastAPI |
| **Google Refresh Token** | Only on FastAPI server (encrypted) | Sliding (7 days in Testing) | Call Gmail/Calendar APIs on behalf of user |
| **Google Access Token** | Only in backend memory | 1 hour | Short-lived, used for actual API calls |

**Key Rule**: Flutter never sees Google tokens. Only session tokens.

---

## 🚨 Security Checklist

Before production:
- [ ] Never commit `.env` (already in .gitignore)
- [ ] On web, migrate to HttpOnly cookies instead of localStorage (Phase 2)
- [ ] Encrypt Google refresh tokens in database with app-level keys
- [ ] Rate limit API endpoints to prevent abuse
- [ ] Validate session token TTL server-side before executing actions
- [ ] Log all approvals to audit table with user, timestamp, outcome
- [ ] Use HTTPS redirect URIs (FastAPI running on https://render.com in prod)

---

## 📞 Architecture Files Reference

- `NEON_FLUTTER_ARCHITECTURE.md` - **MUST READ** design decisions, pitfalls, mitigations
- `NEON_INTEGRATION_SUMMARY.md` - Roadmap, package list, error contracts
- `IMPLEMENTATION_STATUS.md` - What's done, what's next, timeline
- `README.md` - Original project setup and overview
- `backend/main.py` - FastAPI endpoints and credential loading
- `app/lib/providers/core_providers.dart` - Riverpod dependency injection

---

## ✅ Ready to Start?

1. Run backend locally: `uvicorn main:app --reload`
2. Run Flutter web: `flutter run -d chrome --dart-define=API_BASE_URL=http://localhost:8000`
3. Check TODO list above for feature priority
4. Commit frequently with clear commit messages

**Next big milestone**: End-to-end OAuth flow working (sign in → approve meeting → calendar event created).

Good luck! 🚀
