# Neon's Flutter Architecture Integration Summary

## ✅ What Neon Delivered

### 1. **Session Token Management Architecture**
- **AuthSession**: Opaque 30-day session from FastAPI, tracks scopes & Google reconnect status
- **TokenStorageAdapter**: Platform-agnostic interface for secure token persistence
  - `NativeSecureStorageAdapter`: Android Keystore + Windows Credential Manager
  - `WebTokenStorageAdapter`: localStorage with JS interop
- **SessionService**: Coordinates OAuth launch, session validation, sliding refresh, logout

### 2. **HTTP Client Wrapper (ApiClient)**
- Automatic Authorization header injection (Bearer token)
- Single-flight 401 refresh lock (prevents cascading retries)
- Error domain model: `ApiErrorCode` enum + `ApiException` class
- Idempotency-Key support for approve/reject mutations
- Safe logging (never logs tokens, PII, or bodies)
- Differentiates: `unauthorized` (401 → logout) vs `googleReconnectNeeded` (7-day Testing expiry)

### 3. **State Management Strategy**
- **Choice: Riverpod (AsyncNotifier)** over Provider or GetX
- **AuthController**: Manages sign-in, incremental scopes, logout
- **ApprovalTasksController**: Offline-first task list with local cache + mutations
- **Folder structure**: `core/`, `models/`, `providers/`, `ui/screens`, `ui/widgets`

### 4. **Flutter Web Deployment to Render**
- Render build command: Clone Flutter, build web, define static publish path
- CORS headers required: Authorization, Content-Type, Idempotency-Key
- Service worker strategy: Cache-first (assets) vs network-only (API)
- Mitigation: Use GitHub Actions for faster builds (avoid 2-3min Flutter clone per deploy)

### 5. **Approval Card Component Design**
- **State machine**: pending → submittingApprove/submittingReject → approved/rejected/error
- **Task model**: Type (meetingInvite, bill), Status, structured fields per type
- **Widget tree**: Card with header, task details, inline error, action buttons
- **Idempotency**: Stable per-decision key prevents double-execution on retries

---

## 🛠️ Implementation Roadmap

### Phase 1: Core Infrastructure (This session)
- [ ] Create `lib/core/auth/` - SessionService + TokenStorageAdapter
- [ ] Create `lib/core/network/` - ApiClient + ApiException
- [ ] Create `lib/core/models/` - AuthSession, ApprovalTask, UserProfile
- [ ] Create `lib/providers/` - Riverpod core_providers + auth_provider
- [ ] Update `pubspec.yaml` - Add flutter_riverpod, flutter_secure_storage, etc.

### Phase 2: UI Implementation
- [ ] Create `lib/ui/screens/sign_in_screen.dart` - OAuth flow trigger
- [ ] Create `lib/ui/screens/inbox_screen.dart` - Task list (Riverpod consumer)
- [ ] Create `lib/ui/widgets/approval_card.dart` - Interactive card with state
- [ ] Create `lib/ui/widgets/reconnect_google_banner.dart` - 7-day expiry UX
- [ ] Update `lib/main.dart` - App root with Riverpod + routing

### Phase 3: Offline Cache & Deployment
- [ ] Add local task cache (Drift on mobile, IndexedDB on web)
- [ ] Configure Render deployment (build command, static path, CORS)
- [ ] Add GitHub Actions workflow for multi-platform builds (optional)

---

## 📋 Packages to Add

**pubspec.yaml additions:**
```yaml
dependencies:
  flutter_riverpod: ^2.5.0
  riverpod_generator: ^2.5.0
  flutter_secure_storage: ^9.2.0
  uuid: ^4.0.0
  web: ^0.5.0  # for JS interop on web

dev_dependencies:
  build_runner: ^2.4.0
  riverpod_generator: ^2.5.0
```

---

## 🔗 API Contracts (Backend ↔ Frontend)

### Session Lifecycle
1. **GET /oauth/authorize** → Redirect to Google OAuth consent screen
2. **GET /oauth/callback?code=...** → Backend exchanges, returns session_token in redirect
3. **POST /oauth/token** → Validate & refresh session, returns UserProfile + scopes

### Task Management
- **GET /tasks** → List pending/approved/rejected tasks (with optional cache)
- **POST /tasks/{taskId}/approve** → Mark approved, execute side effect (calendar event)
- **POST /tasks/{taskId}/reject** → Mark rejected, cleanup

### Error Responses
- **401 Unauthorized** → `code: "unauthorized"`, UI shows sign-in screen
- **403 Forbidden** → `code: "googleReconnectRequired"`, UI shows "Reconnect Google" banner
- **422 Unprocessable** → `code: "validationError"`, inline error on card

---

## ⚠️ Known Pitfalls & Mitigations

| Pitfall | Mitigation |
|---------|-----------|
| Token leak in Web browser history | Return single-use auth_code, exchange via POST, run `window.history.replaceState()` |
| XSS on Web localStorage | Plan Phase 2 migration to HttpOnly cookies |
| Android Keystore corruption after restore | Catch PlatformException, clear storage, degrade to sign-in screen |
| Windows loopback server hangs | Always use port 0 (OS-assigned), enforce 120s timeout, close listener immediately |
| CORS preflight rejects Idempotency-Key | Explicitly add to allow_headers in FastAPI |
| Infinite 401 loops in ApiClient | Guard with `!isRetry && path != '/oauth/token'` |
| Slow Render builds | Use GitHub Actions artifact caching instead of cloning Flutter each time |

---

## 📌 Next Steps

1. **Create Flutter project structure** (lib/core, lib/providers, etc.)
2. **Implement SessionService + TokenStorageAdapter** (platform-specific)
3. **Implement ApiClient** (integrate with SessionService)
4. **Set up Riverpod providers** (auth_provider, tasks_provider, core_providers)
5. **Build sign-in screen** (OAuth flow trigger)
6. **Build approval card** (task UI + approve/reject)
7. **Test full flow**: Sign in → List tasks → Approve → Verify calendar event created

---

## 📂 File Structure (Target)

```
app/
├── lib/
│   ├── core/
│   │   ├── auth/
│   │   │   ├── auth_session.dart
│   │   │   ├── session_service.dart
│   │   │   ├── token_storage_adapter.dart
│   │   │   ├── token_storage_web.dart (conditional import)
│   │   │   └── token_storage_native.dart (conditional import)
│   │   ├── network/
│   │   │   ├── api_client.dart
│   │   │   ├── api_exception.dart
│   │   │   └── api_error_code.dart
│   │   ├── models/
│   │   │   ├── approval_task.dart
│   │   │   ├── user_profile.dart
│   │   │   └── audit_entry.dart
│   │   └── config/
│   │       └── app_config.dart
│   ├── providers/
│   │   ├── core_providers.dart
│   │   ├── auth_provider.dart
│   │   ├── tasks_provider.dart
│   │   └── ui_state_provider.dart
│   ├── ui/
│   │   ├── screens/
│   │   │   ├── sign_in_screen.dart
│   │   │   ├── inbox_screen.dart
│   │   │   └── settings_screen.dart
│   │   ├── widgets/
│   │   │   ├── approval_card.dart
│   │   │   ├── reconnect_google_banner.dart
│   │   │   └── task_details_section.dart
│   │   └── theme/
│   │       └── app_theme.dart
│   └── main.dart
├── pubspec.yaml
└── web/
    └── index.html
```

---

## 🚀 Ready to Implement?

The architecture is solid and ready for implementation. Start with:
1. Update `pubspec.yaml` with Riverpod, secure_storage, etc.
2. Create `lib/core/auth/session_service.dart` (copy Neon's skeleton)
3. Create `lib/core/network/api_client.dart`
4. Set up providers in `lib/providers/core_providers.dart`
5. Build sign-in screen

Backend is already running with `/oauth/authorize`, `/oauth/callback`, and `/oauth/token` endpoints ready.
