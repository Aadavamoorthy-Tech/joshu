User responded: Flutter UI Architecture â€” Personal AI Chief of Staff (Joshu)
Table of Contents
Task 1: Session Token Management Architecture
Task 2: HTTP Client Wrapper (ApiClient)
Task 3: State Management Strategy
Task 4: Flutter Web Deployment to Render
Task 5: Approval Card Component Design
Next Steps (Design-to-Implementation Roadmap)
Task 1: Session Token Management Architecture
Architectural Design
Separate two distinct token lifecycles so the UX stays predictable across platforms:
Joshu App Session (session_token, 30-day TTL): Authenticates Flutter â†” FastAPI. Stored locally per platform behind a single TokenStorageAdapter interface.
Google OAuth Connection (Backend-managed, 7-day refresh expiry in Testing mode): Never stored in Flutter. FastAPI reports connection health (connected, scopes_missing, reconnect_required) on /oauth/token so the user stays signed into Joshu even when Google Testing tokens expire.
Class Structure & Code Skeleton
Dart
/// Represents the active Joshu session returned by FastAPI.
class AuthSession {
  /// Opaque bearer token issued by FastAPI (30-day TTL).
  final String sessionToken;

  /// Expiration timestamp in UTC from FastAPI `sessions.expires_at`.
  final DateTime expiresAt;

  /// Granted Google scopes currently active on the backend.
  final Set<String> grantedScopes;

  /// True when backend Google refresh token hit `invalid_grant` (e.g., 7-day Testing cap).
  final bool googleReconnectRequired;

  const AuthSession({
    required this.sessionToken,
    required this.expiresAt,
    required this.grantedScopes,
    this.googleReconnectRequired = false,
  });

  /// Returns true if the local session is expired or within a 5-minute safety buffer.
  bool get isExpiredOrNearExpiry =>
      DateTime.now().toUtc().isAfter(expiresAt.subtract(const Duration(minutes: 5)));
}

/// Platform-agnostic secure key-value contract for session persistence.
abstract interface class TokenStorageAdapter {
  /// Reads the stored session JSON payload, or null if absent.
  Future<String?> read(String key);

  /// Persists the serialized session securely for the current platform.
  Future<void> write(String key, String value);

  /// Permanently removes the stored key (used on logout or corruption).
  Future<void> delete(String key);
}

/// Mobile & Windows implementation backed by OS keychains via `flutter_secure_storage`.
/// - Android: EncryptedSharedPreferences + Android Keystore (AES-GCM).
/// - Windows: Windows Credential Manager / DPAPI (CredWrite / CredRead).
class NativeSecureStorageAdapter implements TokenStorageAdapter {
  // Inject FlutterSecureStorage configured with AndroidOptions(encryptedSharedPreferences: true)
  @override
  Future<String?> read(String key) async {
    // try { return await _storage.read(key: key); }
    // on PlatformException { await _storage.deleteAll(); return null; }
    throw UnimplementedError();
  }

  @override
  Future<void> write(String key, String value) async {
    throw UnimplementedError();
  }

  @override
  Future<void> delete(String key) async {
    throw UnimplementedError();
  }
}

/// Web implementation using `package:web` (`window.localStorage`) behind conditional import.
/// Note: For higher XSS resistance in production, migrate Web sessions to FastAPI
/// `HttpOnly; Secure; SameSite=Lax` cookies while keeping this adapter for native clients.
class WebTokenStorageAdapter implements TokenStorageAdapter {
  @override
  Future<String?> read(String key) async {
    // return web.window.localStorage.getItem(key);
    throw UnimplementedError();
  }

  @override
  Future<void> write(String key, String value) async {
    // web.window.localStorage.setItem(key, value);
    throw UnimplementedError();
  }

  @override
  Future<void> delete(String key) async {
    // web.window.localStorage.removeItem(key);
    throw UnimplementedError();
  }
}

/// Coordinates OAuth launch, session persistence, sliding refresh, and logout.
class SessionService {
  static const _storageKey = 'joshu_auth_session_v1';

  final TokenStorageAdapter _storage;
  AuthSession? _cached;

  SessionService(this._storage);

  /// Restores and validates an existing session on app startup.
  /// Clears storage and returns null if missing, corrupted, or expired.
  Future<AuthSession?> restoreSession() async {
    try {
      final raw = await _storage.read(_storageKey);
      if (raw == null) return null;
      final session = _decodeSession(raw);
      if (session.isExpiredOrNearExpiry) {
        await clearSession();
        return null;
      }
      _cached = session;
      return session;
    } catch (_) {
      await clearSession();
      return null;
    }
  }

  /// Launches Google OAuth via FastAPI broker with incremental scope support.
  /// - Sign-in: `scopes = ['openid', 'email', 'profile']`
  /// - Connect Workspace later: `scopes = ['gmail.readonly', 'calendar.events']`
  Future<AuthSession> launchOAuthFlow({
    required List<String> scopes,
    required String baseUrl,
  }) async {
    // 1. Web: redirect or popup to `$baseUrl/oauth/authorize?scopes=...&platform=web`
    // 2. Windows: bind `HttpServer.bind(InternetAddress.loopbackIPv4, 0)`, open system browser
    //    to `$baseUrl/oauth/authorize?platform=windows&port=${server.port}`, capture one-time code
    // 3. Android: Custom Tabs (`flutter_web_auth_2`) or Credential Manager + AuthorizationClient
    // 4. Exchange one-time code via POST `$baseUrl/oauth/exchange` -> saveSession()
    throw UnimplementedError();
  }

  /// Returns current bearer token from memory or secure storage.
  Future<String?> getToken() async {
    if (_cached != null && !_cached!.isExpiredOrNearExpiry) {
      return _cached!.sessionToken;
    }
    final restored = await restoreSession();
    return restored?.sessionToken;
  }

  /// Calls POST /oauth/token (or /oauth/refresh) to validate and slide the 30-day session.
  /// Returns null if the backend rejects the session (401).
  Future<AuthSession?> validateOrRefreshSession({
    required Future<AuthSession?> Function(String token) remoteValidate,
  }) async {
    final token = await getToken();
    if (token == null) return null;
    final updated = await remoteValidate(token);
    if (updated == null) {
      await clearSession();
      return null;
    }
    await saveSession(updated);
    return updated;
  }

  /// Persists session atomically to memory and platform storage.
  Future<void> saveSession(AuthSession session) async {
    _cached = session;
    await _storage.write(_storageKey, _encodeSession(session));
  }

  /// Clears in-memory and persisted credentials on logout.
  Future<void> clearSession() async {
    _cached = null;
    await _storage.delete(_storageKey);
  }

  AuthSession _decodeSession(String raw) => throw UnimplementedError();
  String _encodeSession(AuthSession session) => throw UnimplementedError();
}
Platform-Specific Implementation Notes
Conditional Imports: Export createTokenStorageAdapter() using dart.library.js_interop (selects WebTokenStorageAdapter) vs dart.library.io (selects NativeSecureStorageAdapter) so Web builds never pull in native FFI plugins.
Android Keystore Corruption: After Android app backup/restore across devices, Keystore decryption can throw BadPaddingException. Catch PlatformException, clear storage, and degrade cleanly to the sign-in screen.
Windows Loopback Server: Always bind InternetAddress.loopbackIPv4 (127.0.0.1, port 0 for OS-assigned ephemeral port), enforce a 120-second timeout, and immediately close the listener after receiving the callback.
Rationale & Pitfalls
Why: FastAPI stays the sole custodian of Google OAuth secrets and refresh tokens; Flutter only handles revocable app sessions.
Pitfall â€” Token Leak in Browser History: Returning ?session_token=... in Web redirect URLs leaks tokens into browser history and proxy logs. Mitigation: Return a 60-second single-use auth_code in the redirect, exchange it via POST /oauth/exchange, and immediately run window.history.replaceState to strip query parameters.
Pitfall â€” XSS on Web localStorage: Any XSS bug can read localStorage. Mitigation: Enforce strict CSP headers on Render and plan a Phase 2 upgrade to HttpOnly session cookies on Web while keeping Bearer tokens for Android/Windows.
Task 2: HTTP Client Wrapper (ApiClient)
Architectural Design
ApiClient wraps http.Client with:
Automatic Authorization: Bearer <session_token> injection and Idempotency-Key support on mutating requests (critical for approve/reject).
A single-flight 401 refresh lock (Completer<bool>) so 5 parallel API calls failing with 401 trigger only one validation/refresh call before retrying once.
Explicit differentiation between sessionExpired (401 â†’ force logout) and googleReconnectRequired (e.g., 428/403 with backend error code google_token_expired from the 7-day Testing mode limit â†’ keep user logged in, show reconnect prompt).
Safe non-sensitive logging (method, path, status, duration onlyâ€”never headers or email bodies).
Error Domain Model & Code Skeleton
Dart
import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

/// Domain-level error categories mapped from HTTP, CORS, and network failures.
enum ApiErrorCode {
  unauthorized,           // 401: Joshu session invalid or expired -> sign out
  googleReconnectNeeded,  // 428/403: Google refresh token expired (7-day Testing cap)
  scopeUpgradeRequired,   // 403: Incremental Gmail/Calendar scope not yet granted
  forbidden,              // 403: Tenant isolation or backend policy violation
  validationError,        // 400/422: Invalid request payload
  conflict,               // 409: Task already approved/rejected/expired
  rateLimited,            // 429: Retry after backoff
  corsOrNetworkBlocked,   // Web CORS block or offline device
  timeout,                // Request exceeded timeout
  serverError,            // 5xx backend error
  unknown,
}

/// Typed exception surfaced to providers and UI widgets.
class ApiException implements Exception {
  final ApiErrorCode code;
  final String message;
  final int? statusCode;
  final String? serverRuleId;

  const ApiException({
    required this.code,
    required this.message,
    this.statusCode,
    this.serverRuleId,
  });

  bool get isRetryable =>
      code == ApiErrorCode.timeout ||
      code == ApiErrorCode.corsOrNetworkBlocked ||
      code == ApiErrorCode.serverError ||
      code == ApiErrorCode.rateLimited;

  @override
  String toString() => 'ApiException($code, status=$statusCode): $message';
}

/// Centralized HTTP wrapper with bearer injection, single-flight 401 retry, and error mapping.
class ApiClient {
  final String baseUrl;
  final http.Client _http;
  final SessionService _sessionService;
  final VoidCallback onUnauthorizedSession;
  final VoidCallback onGoogleReconnectRequired;

  Completer<bool>? _refreshInFlight;

  ApiClient({
    required this.baseUrl,
    required SessionService sessionService,
    required this.onUnauthorizedSession,
    required this.onGoogleReconnectRequired,
    http.Client? httpClient,
  })  : _sessionService = sessionService,
        _http = httpClient ?? http.Client();

  /// Sends an authenticated GET request and decodes JSON.
  Future<Map<String, dynamic>> getJson(
    String path, {
    Map<String, String>? queryParameters,
  }) =>
      _send('GET', path, queryParameters: queryParameters);

  /// Sends an authenticated POST request with optional idempotency key.
  Future<Map<String, dynamic>> postJson(
    String path, {
    Map<String, dynamic>? body,
    String? idempotencyKey,
  }) =>
      _send('POST', path, body: body, idempotencyKey: idempotencyKey);

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Map<String, String>? queryParameters,
    Map<String, dynamic>? body,
    String? idempotencyKey,
    bool isRetry = false,
  }) async {
    final uri = Uri.parse('$baseUrl$path').replace(queryParameters: queryParameters);
    final stopwatch = Stopwatch()..start();

    try {
      final token = await _sessionService.getToken();
      final headers = <String, String>{
        'Accept': 'application/json',
        if (body != null) 'Content-Type': 'application/json',
        if (token != null) 'Authorization': 'Bearer $token',
        if (idempotencyKey != null) 'Idempotency-Key': idempotencyKey,
      };

      final request = http.Request(method, uri)..headers.addAll(headers);
      if (body != null) {
        request.body = jsonEncode(body);
      }

      final streamed = await _http.send(request).timeout(const Duration(seconds: 20));
      final response = await http.Response.fromStream(streamed);
      stopwatch.stop();

      _logSafe(method, uri.path, response.statusCode, stopwatch.elapsedMilliseconds);

      // Single-flight 401 retry: validate/refresh session once before forcing logout.
      if (response.statusCode == 401 && !isRetry && path != '/oauth/token') {
        final refreshed = await _attemptSingleFlightRefresh();
        if (refreshed) {
          return _send(
            method,
            path,
            queryParameters: queryParameters,
            body: body,
            idempotencyKey: idempotencyKey,
            isRetry: true,
          );
        }
        onUnauthorizedSession();
      }

      return _handleResponse(response);
    } on TimeoutException {
      throw const ApiException(
        code: ApiErrorCode.timeout,
        message: 'The server took too long to respond. Please try again.',
      );
    } on http.ClientException catch (e) {
      // On Flutter Web, CORS preflight failures surface as `ClientException: XMLHttpRequest error`.
      throw ApiException(
        code: ApiErrorCode.corsOrNetworkBlocked,
        message: kIsWeb
            ? 'Unable to reach the server. Check your connection or backend CORS configuration.'
            : 'Network unavailable. Showing cached data if available.',
      );
    }
  }

  Future<bool> _attemptSingleFlightRefresh() async {
    if (_refreshInFlight != null) return _refreshInFlight!.future;
    final completer = Completer<bool>();
    _refreshInFlight = completer;

    try {
      final session = await _sessionService.validateOrRefreshSession(
        remoteValidate: (token) async {
          // POST /oauth/token to check validity & refresh expiry
          return null;
        },
      );
      final ok = session != null;
      completer.complete(ok);
      return ok;
    } catch (_) {
      completer.complete(false);
      return false;
    } finally {
      _refreshInFlight = null;
    }
  }

  Map<String, dynamic> _handleResponse(http.Response response) {
    final decoded = response.body.isNotEmpty
        ? jsonDecode(response.body) as Map<String, dynamic>
        : <String, dynamic>{};

    if (response.statusCode >= 200 && response.statusCode < 300) {
      return decoded;
    }

    final errorKey = decoded['error_code'] as String?;
    final detail = decoded['detail']?.toString() ?? 'Request failed';

    if (errorKey == 'google_token_expired') {
      onGoogleReconnectRequired();
      throw ApiException(
        code: ApiErrorCode.googleReconnectNeeded,
        statusCode: response.statusCode,
        message: 'Your Google connection expired. Reconnect Google to resume syncing.',
      );
    }

    if (errorKey == 'google_scope_missing') {
      throw ApiException(
        code: ApiErrorCode.scopeUpgradeRequired,
        statusCode: response.statusCode,
        message: 'Additional Google permissions are required for this action.',
      );
    }

    final code = switch (response.statusCode) {
      401 => ApiErrorCode.unauthorized,
      403 => ApiErrorCode.forbidden,
      400 || 422 => ApiErrorCode.validationError,
      409 => ApiErrorCode.conflict,
      429 => ApiErrorCode.rateLimited,
      >= 500 => ApiErrorCode.serverError,
      _ => ApiErrorCode.unknown,
    };

    throw ApiException(code: code, statusCode: response.statusCode, message: detail);
  }

  /// Logs only non-sensitive metadata (never tokens, query params, or PII bodies).
  void _logSafe(String method, String path, int status, int elapsedMs) {
    if (kDebugMode) {
      debugPrint('[ApiClient] $method $path -> $status (${elapsedMs}ms)');
    }
  }

  void close() => _http.close();
}
Rationale & Pitfalls
Why: Centralizes all auth headers, idempotency keys, and backend policy error codes in one auditable place so UI screens never parse raw HTTP statuses.
Pitfall â€” Silent CORS Failures on Web: Browsers intentionally hide CORS error details from JavaScript, returning status 0 / XMLHttpRequest error. Mitigation: Map http.ClientException on Web to corsOrNetworkBlocked and verify OPTIONS preflight headers in FastAPI (Task 4).
Pitfall â€” Infinite 401 Loops: Retrying /oauth/token on 401 causes recursion. Mitigation: Guard with !isRetry && path != '/oauth/token'.
Task 3: State Management Strategy
Recommendation: Riverpod (flutter_riverpod)
Criterion	Riverpod (AsyncNotifier)	Provider (ChangeNotifier)	GetX
Dependency injection (SessionService â†’ ApiClient â†’ Repos)	Clean, compile-time safe, no BuildContext needed	Clunky ProxyProvider chains	Global mutable singletons
Testability (mocking FastAPI & offline cache)	Override any provider in 1 line in unit/widget tests	Requires widget tree pumping	Hard to isolate state
Async loading / error / offline states	Native AsyncValue<T> (data, loading, error + stale data retention)	Manual boolean flags per screen	Manual observables
Multi-platform scale (Web, Android, Windows)	Ideal for enterprise SaaS	Fine for tiny apps, fragile as workflows grow	Poor long-term maintainability
Folder Structure
Text
lib/
â”œâ”€â”€ core/
â”‚   â”œâ”€â”€ config/          # AppConfig (API_BASE_URL, env flags)
â”‚   â”œâ”€â”€ auth/            # SessionService, TokenStorageAdapter (web/native)
â”‚   â”œâ”€â”€ network/         # ApiClient, ApiException
â”‚   â””â”€â”€ cache/           # LocalTaskCache (SQLite/Drift on mobile/desktop, IndexedDB/memory on web)
â”œâ”€â”€ models/
â”‚   â”œâ”€â”€ user_profile.dart
â”‚   â”œâ”€â”€ approval_task.dart
â”‚   â””â”€â”€ audit_entry.dart
â”œâ”€â”€ providers/
â”‚   â”œâ”€â”€ core_providers.dart       # config, storage, sessionService, apiClient
â”‚   â”œâ”€â”€ auth_provider.dart        # AuthState + AuthController
â”‚   â”œâ”€â”€ tasks_provider.dart       # ApprovalTasksController (offline-first cache + mutations)
â”‚   â””â”€â”€ ui_state_provider.dart    # active tab, task status filter, banner/error state
â””â”€â”€ ui/
    â”œâ”€â”€ screens/         # sign_in_screen.dart, inbox_screen.dart, settings_screen.dart
    â””â”€â”€ widgets/         # approval_card.dart, reconnect_google_banner.dart
Riverpod Provider Skeletons
Dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// Tracks authentication, user profile, and Google Workspace connection health.
enum AuthStatus { loading, signedOut, signedIn }

class AuthState {
  final AuthStatus status;
  final UserProfile? user;
  final Set<String> grantedScopes;
  final bool googleReconnectRequired;
  final String? errorMessage;

  const AuthState({
    required this.status,
    this.user,
    this.grantedScopes = const {},
    this.googleReconnectRequired = false,
    this.errorMessage,
  });

  bool get hasWorkspaceScopes =>
      grantedScopes.contains('https://www.googleapis.com/auth/gmail.readonly') &&
      grantedScopes.contains('https://www.googleapis.com/auth/calendar.events');

  AuthState copyWith({
    AuthStatus? status,
    UserProfile? user,
    Set<String>? grantedScopes,
    bool? googleReconnectRequired,
    String? errorMessage,
  }) =>
      AuthState(
        status: status ?? this.status,
        user: user ?? this.user,
        grantedScopes: grantedScopes ?? this.grantedScopes,
        googleReconnectRequired: googleReconnectRequired ?? this.googleReconnectRequired,
        errorMessage: errorMessage,
      );
}

/// Manages sign-in, incremental Google scope upgrades, and logout.
class AuthController extends Notifier<AuthState> {
  @override
  AuthState build() {
    Future.microtask(_bootstrap);
    return const AuthState(status: AuthStatus.loading);
  }

  Future<void> _bootstrap() async {
    final session = await ref.read(sessionServiceProvider).restoreSession();
    if (session == null) {
      state = const AuthState(status: AuthStatus.signedOut);
      return;
    }
    try {
      final profileJson = await ref.read(apiClientProvider).postJson('/oauth/token');
      state = AuthState(
        status: AuthStatus.signedIn,
        user: UserProfile.fromJson(profileJson),
        grantedScopes: session.grantedScopes,
        googleReconnectRequired: session.googleReconnectRequired,
      );
    } on ApiException {
      await ref.read(sessionServiceProvider).clearSession();
      state = const AuthState(status: AuthStatus.signedOut);
    }
  }

  /// Step 1 (Incremental Auth): Sign in with basic profile scopes only.
  Future<void> signInWithGoogle() async {
    state = state.copyWith(status: AuthStatus.loading, errorMessage: null);
    // Launch SessionService.launchOAuthFlow(scopes: ['openid', 'email', 'profile'])
  }

  /// Step 2 (Incremental Auth): Request Gmail read + Calendar write when user connects services.
  Future<void> connectGoogleWorkspace() async {
    // Launch SessionService.launchOAuthFlow(scopes: [gmail.readonly, calendar.events])
  }

  /// Triggered by ApiClient when backend reports 7-day Testing token expiry.
  void markGoogleReconnectRequired() {
    state = state.copyWith(googleReconnectRequired: true);
  }

  Future<void> signOut() async {
    await ref.read(sessionServiceProvider).clearSession();
    await ref.read(localTaskCacheProvider).clearAll(); // Prevent cross-user cache leakage
    state = const AuthState(status: AuthStatus.signedOut);
  }
}

final authControllerProvider =
    NotifierProvider<AuthController, AuthState>(AuthController.new);

/// Offline-first controller for pending, approved, and rejected approval tasks.
class ApprovalTasksController extends AsyncNotifier<List<ApprovalTask>> {
  @override
  Future<List<ApprovalTask>> build() async {
    final cache = ref.read(localTaskCacheProvider);
    final cachedTasks = await cache.loadTasks();

    // Emit cached tasks immediately on mobile/desktop while refreshing from FastAPI.
    if (cachedTasks.isNotEmpty) {
      state = AsyncData(cachedTasks);
    }

    try {
      final res = await ref.read(apiClientProvider).getJson('/tasks');
      final fresh = (res['tasks'] as List)
          .map((e) => ApprovalTask.fromJson(e as Map<String, dynamic>))
          .toList();
      await cache.saveTasks(fresh);
      return fresh;
    } on ApiException catch (e) {
      // Offline-first fallback: return cached list if network is unavailable.
      if (e.code == ApiErrorCode.corsOrNetworkBlocked && cachedTasks.isNotEmpty) {
        return cachedTasks;
      }
      rethrow;
    }
  }

  /// Submits an explicit Approve or Reject decision with an idempotency key.
  /// Never optimistically assumes success for external side effects (Calendar/Payments).
  Future<void> decideTask({
    required String taskId,
    required bool approve,
    required String idempotencyKey,
  }) async {
    final action = approve ? 'approve' : 'reject';
    final res = await ref.read(apiClientProvider).postJson(
          '/tasks/$taskId/$action',
          idempotencyKey: idempotencyKey,
        );
    final updatedTask = ApprovalTask.fromJson(res);
    final current = state.valueOrNull ?? [];
    final nextList = [
      for (final t in current) if (t.taskId == taskId) updatedTask else t,
    ];
    await ref.read(localTaskCacheProvider).saveTasks(nextList);
    state = AsyncData(nextList);
  }
}

final approvalTasksProvider =
    AsyncNotifierProvider<ApprovalTasksController, List<ApprovalTask>>(
        ApprovalTasksController.new);

/// UI filter and navigation state kept strictly separate from server data.
enum TaskFilter { pending, approved, rejected }

final taskFilterProvider = StateProvider<TaskFilter>((ref) => TaskFilter.pending);
Rationale & Pitfalls
Why no optimistic approval: Approving creates a real Google Calendar event (or future payment). Showing "Approved" before FastAPI confirms backend policy enforcement + Google API success violates the trust model.
Pitfall â€” Cross-User Offline Cache Leakage: If User A signs out and User B signs in on a shared Windows/Android device, cached tasks could leak. Mitigation: Key cached records by google_id and wipe local cache on signOut().
Task 4: Flutter Web Deployment to Render
Step-by-Step Deployment Checklist
Standardize environments (dev, staging, prod): Never hardcode http://localhost:8000 in Dart; inject API_BASE_URL via --dart-define (compile-time) with optional window.__JOSHU_CONFIG__ override in web/index.html (runtime).
Build release bundle:
Bash
flutter build web --release \
  --dart-define=API_BASE_URL=https://joshu-api.onrender.com \
  --dart-define=APP_ENV=prod
Host as a Render Static Site (or Netlify) with an SPA rewrite rule (/* â†’ /index.html, HTTP 200) so OAuth callback paths like /auth/callback don't 404 on hard reload.
Update Google Cloud Console (joshu-515708): Add the Render backend callback (https://joshu-api.onrender.com/auth/google/callback) to Authorized Redirect URIs and the Flutter Web URL (https://joshu-web.onrender.com) to Authorized JavaScript Origins.
Lock down FastAPI CORS to exact origins (never * when allow_credentials=True).
Configure cache headers so index.html, flutter_bootstrap.js, and env-config.js are never stale in user browsers after a release.
web/index.html Environment Configuration
Html
<!DOCTYPE html>
<html>
<head>
  <base href="$FLUTTER_BASE_HREF">
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Joshu â€” Personal AI Chief of Staff</title>

  <!-- Optional runtime config generated at build/deploy time for env promotion -->
  <script>
    window.__JOSHU_CONFIG__ = {
      API_BASE_URL: "https://joshu-api.onrender.com",
      APP_ENV: "prod"
    };
  </script>
</head>
<body>
  <script src="flutter_bootstrap.js" async></script>
</body>
</html>
Dart
/// Reads compile-time `--dart-define` first, falling back to `window.__JOSHU_CONFIG__` on Web.
class AppConfig {
  static const _compiledApiBaseUrl = String.fromEnvironment('API_BASE_URL');

  static String get apiBaseUrl {
    if (_compiledApiBaseUrl.isNotEmpty) return _compiledApiBaseUrl;
    // On Web, read window.__JOSHU_CONFIG__.API_BASE_URL via package:web JS interop.
    return 'http://localhost:8000';
  }
}
render.yaml Blueprint (Backend + Worker + PostgreSQL + Flutter Web)
Yaml
databases:
  - name: joshu-db
    plan: starter

services:
  # 1. FastAPI Backend Web Service
  - type: web
    name: joshu-api
    runtime: python
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: uvicorn main:app --host 0.0.0.0 --port $PORT
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: joshu-db
          property: connectionString
      - key: BASE_URL
        value: https://joshu-api.onrender.com
      - key: CORS_ALLOWED_ORIGINS
        value: https://joshu-web.onrender.com
      - key: FLUTTER_REDIRECT_URI
        value: https://joshu-web.onrender.com/auth/callback
      - key: GOOGLE_CLIENT_ID
        sync: false
      - key: GOOGLE_CLIENT_SECRET
        sync: false
      - key: ENCRYPTION_KEY
        sync: false

  # 2. Background Worker (Gmail Polling & Stateful Workflow Processing)
  - type: worker
    name: joshu-worker
    runtime: python
    rootDir: backend
    buildCommand: pip install -r requirements.txt
    startCommand: python worker.py
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: joshu-db
          property: connectionString
      - key: ENCRYPTION_KEY
        sync: false

  # 3. Flutter Web Static Site
  - type: web
    name: joshu-web
    runtime: static
    rootDir: app
    buildCommand: |
      git clone https://github.com/flutter/flutter.git -b stable --depth 1 $HOME/flutter
      export PATH="$HOME/flutter/bin:$PATH"
      flutter pub get
      flutter build web --release --dart-define=API_BASE_URL=https://joshu-api.onrender.com
    staticPublishPath: build/web
    headers:
      - path: /index.html
        name: Cache-Control
        value: no-cache, no-store, must-revalidate
      - path: /flutter_bootstrap.js
        name: Cache-Control
        value: no-cache
      - path: /flutter_service_worker.js
        name: Cache-Control
        value: no-cache
    routes:
      - type: rewrite
        source: /*
        destination: /index.html
Required FastAPI CORS Headers
Python
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Exact origins: ["https://joshu-web.onrender.com", "http://localhost:8080"]
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    expose_headers=["X-Request-Id"],
    max_age=600,
)
Headers returned by FastAPI on preflight (OPTIONS) and API responses:
Access-Control-Allow-Origin: https://joshu-web.onrender.com
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, Idempotency-Key
Access-Control-Allow-Credentials: true
Service Worker Caching Strategy
Cache-first for immutable hashed static assets (canvaskit/, fonts, icons).
Network-only (never cache) for /oauth/*, /tasks/*, and any authenticated API request so stale approval states or tokens never replay from cache.
No-cache on bootstrap files (index.html, flutter_bootstrap.js, flutter_service_worker.js)â€”or pass --pwa-strategy=none during early rapid iteration so users never get stuck on an old Flutter Web bundle after an API schema change.
Pitfalls & Mitigations
Pitfall â€” Slow Render Static Builds: Cloning Flutter on every Render build adds 2â€“3 minutes. Mitigation: Build Flutter Web in GitHub Actions and publish artifacts (or deploy static output to Netlify/Cloudflare Pages) once release cadence increases.
Pitfall â€” Missing Idempotency-Key in allow_headers: Causes browser CORS preflight to reject all Approve/Reject POST calls. Explicitly whitelist it in FastAPI.
Task 5: Approval Card Component Design
Data Model & State Transitions
State machine per card:
pending â†’ (submittingApprove | submittingReject) â†’ approved / rejected OR error (returns to retryable pending with inline error message, reusing the same idempotencyKey on retry so backend never creates duplicate Calendar events).
Dart
enum TaskType { meetingInvite, bill }
enum TaskStatus { pending, approved, rejected, expired }

/// Structured payload rendered inside an ApprovalCard.
class ApprovalTask {
  final String taskId;
  final TaskType type;
  final TaskStatus status;
  final String title;
  final String? description;
  final DateTime createdAt;
  final DateTime expiresAt;

  // Meeting Invite fields
  final String? organizer;
  final DateTime? startTime;
  final DateTime? endTime;
  final List<String> attendees;
  final String? calendarConflictNote;

  // Bill fields (Phase 2 ready)
  final String? vendor;
  final int? amountCents;
  final String? currency;
  final DateTime? dueDate;
  final bool? payeeAllowlisted;

  const ApprovalTask({
    required this.taskId,
    required this.type,
    required this.status,
    required this.title,
    this.description,
    required this.createdAt,
    required this.expiresAt,
    this.organizer,
    this.startTime,
    this.endTime,
    this.attendees = const [],
    this.calendarConflictNote,
    this.vendor,
    this.amountCents,
    this.currency,
    this.dueDate,
    this.payeeAllowlisted,
  });

  factory ApprovalTask.fromJson(Map<String, dynamic> json) =>
      throw UnimplementedError();
}
Widget Tree & Component Skeleton
Dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:uuid/uuid.dart';

/*
Widget Tree Layout (Responsive: full-width mobile, max 640px card on Web/Windows):
Card (1px neutral hairline border, flat elevation)
â””â”€â”€ Padding (16px)
    â””â”€â”€ Column (crossAxisAlignment: start, spacing: 12px)
        â”œâ”€â”€ Row (Header)
        â”‚   â”œâ”€â”€ Text (Category Â· Relative time, muted unboxed metadata)
        â”‚   â””â”€â”€ Text (Status label: Pending / Approved / Rejected)
        â”œâ”€â”€ Text (Task title, SemiBold 16px)
        â”œâ”€â”€ _TaskDetailsSection (type-specific structured key-value rows)
        â”‚   â”œâ”€â”€ [Meeting]: Organizer, Date & Time, Attendees (+ Conflict notice if any)
        â”‚   â””â”€â”€ [Bill]: Vendor, Amount (tabular figures), Due Date, Payee Allowlist status
        â”œâ”€â”€ [Conditional] Inline Error Banner (icon + readable message + Retry hint)
        â””â”€â”€ [If pending] Row (Action Bar, aligned end, spacing: 8px)
            â”œâ”€â”€ OutlinedButton ("Reject", disabled while submitting)
            â””â”€â”€ FilledButton ("Approve", shows 16px CircularProgressIndicator when loading)
*/

/// Interactive card that enforces explicit human approval before backend side effects.
class ApprovalCard extends ConsumerStatefulWidget {
  final ApprovalTask task;

  const ApprovalCard({super.key, required this.task});

  @override
  ConsumerState<ApprovalCard> createState() => _ApprovalCardState();
}

class _ApprovalCardState extends ConsumerState<ApprovalCard> {
  bool _isSubmitting = false;
  bool? _pendingActionApprove;
  String? _errorMessage;

  /// Stable idempotency key per decision attempt so network retries cannot double-execute.
  String? _activeIdempotencyKey;

  Future<void> _handleDecision(bool approve) async {
    if (_isSubmitting || widget.task.status != TaskStatus.pending) return;

    setState(() {
      _isSubmitting = true;
      _pendingActionApprove = approve;
      _errorMessage = null;
      _activeIdempotencyKey ??= 'dec_${widget.task.taskId}_${const Uuid().v4()}';
    });

    try {
      await ref.read(approvalTasksProvider.notifier).decideTask(
            taskId: widget.task.taskId,
            approve: approve,
            idempotencyKey: _activeIdempotencyKey!,
          );
      _activeIdempotencyKey = null;
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
        // Clear key only on non-retryable conflicts/validation errors
        if (!e.isRetryable) _activeIdempotencyKey = null;
      });
    } finally {
      if (mounted) {
        setState(() {
          _isSubmitting = false;
          _pendingActionApprove = null;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final task = widget.task;
    final theme = Theme.of(context);

    return Card(
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(12),
        side: BorderSide(color: theme.colorScheme.outlineVariant),
      ),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            // 1. Metadata & status header
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Text(
                  task.type == TaskType.meetingInvite ? 'Meeting Invite' : 'Bill Payment',
                  style: theme.textTheme.labelMedium?.copyWith(
                    color: theme.colorScheme.onSurfaceVariant,
                  ),
                ),
                Text(
                  task.status.name.toUpperCase(),
                  style: theme.textTheme.labelMedium,
                ),
              ],
            ),
            const SizedBox(height: 8),

            // 2. Primary title
            Text(task.title, style: theme.textTheme.titleMedium),
            const SizedBox(height: 12),

            // 3. Domain-specific details
            if (task.type == TaskType.meetingInvite) ...[
              _DetailRow(label: 'Organizer', value: task.organizer ?? 'Unknown'),
              _DetailRow(
                label: 'Time',
                value: '${task.startTime?.toLocal()} â€“ ${task.endTime?.toLocal()}',
              ),
              _DetailRow(label: 'Attendees', value: task.attendees.join(', ')),
              if (task.calendarConflictNote != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(
                    'Conflict: ${task.calendarConflictNote}',
                    style: theme.textTheme.bodySmall?.copyWith(color: Colors.amber.shade900),
                  ),
                ),
            ] else ...[
              _DetailRow(label: 'Vendor', value: task.vendor ?? 'Unknown'),
              _DetailRow(
                label: 'Amount',
                value: _formatMoney(task.amountCents, task.currency ?? 'USD'),
              ),
              _DetailRow(label: 'Due Date', value: '${task.dueDate?.toLocal()}'),
            ],

            // 4. Inline error feedback
            if (_errorMessage != null) ...[
              const SizedBox(height: 12),
              Semantics(
                liveRegion: true,
                child: Row(
                  children: [
                    Icon(Icons.error_outline, size: 16, color: theme.colorScheme.error),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        _errorMessage!,
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: theme.colorScheme.error,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],

            // 5. Explicit Approve / Reject controls (pending tasks only)
            if (task.status == TaskStatus.pending) ...[
              const SizedBox(height: 16),
              Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  OutlinedButton(
                    onPressed: _isSubmitting ? null : () => _handleDecision(false),
                    child: _isSubmitting && _pendingActionApprove == false
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Text('Reject'),
                  ),
                  const SizedBox(width: 8),
                  FilledButton(
                    onPressed: _isSubmitting ? null : () => _handleDecision(true),
                    child: _isSubmitting && _pendingActionApprove == true
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Text('Approve'),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  String _formatMoney(int? cents, String currency) {
    if (cents == null) return 'â€”';
    return '$currency ${(cents / 100).toStringAsFixed(2)}';
  }
}

class _DetailRow extends StatelessWidget {
  final String label;
  final String value;

  const _DetailRow({required this.label, required this.value});

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 84,
            child: Text(
              label,
              style: theme.textTheme.bodySmall?.copyWith(
                color: theme.colorScheme.onSurfaceVariant,
              ),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: theme.textTheme.bodySmall?.copyWith(
                fontFeatures: const [FontFeature.tabularFigures()],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
Rationale & Pitfalls
Why local ConsumerStatefulWidget for in-flight state: Keeps submitting/error spinners scoped to the exact card being clicked rather than locking the entire approval list.
Pitfall â€” Double-Click Creating Duplicate Calendar Events: Users double-click Approve on slow networks. Mitigation: Disable both buttons immediately on tap AND send a persistent Idempotency-Key header enforced by FastAPI so retries return the already-created event cleanly.
Next Steps (Design-to-Implementation Roadmap)
Backend Alignment (Prerequisite):
Rotate the Google Client Secret and delete /temp/.
Fix backend/main.py: use "web" client config, verify state + ID token with verify_oauth2_token, match /auth/google/callback, add POST /oauth/exchange for one-time codes, and add GET /tasks, POST /tasks/{id}/approve, POST /tasks/{id}/reject with Idempotency-Key support.
Task 1 â†’ Implement SessionService & Storage Adapters:
Add flutter_secure_storage, web, url_launcher, and flutter_web_auth_2 to pubspec.yaml.
Implement conditional-import TokenStorageAdapter + Windows loopback listener + incremental scope launch.
Task 2 â†’ Implement ApiClient & Error Domain:
Add http to pubspec.yaml.
Implement ApiClient, ApiException, single-flight 401 refresh, and google_token_expired detection (7-day Testing mode recovery).
Task 3 â†’ Wire Riverpod State & Offline Cache:
Add flutter_riverpod and drift (or sqflite / hive_ce) to pubspec.yaml.
Implement AuthController, ApprovalTasksController (with tenant-scoped offline cache), and ReconnectGoogleBanner.
Task 5 â†’ Build ApprovalCard & Inbox Screen:
Add uuid and intl to pubspec.yaml.
Build responsive inbox layout (single-column on Android, centered max-width feed on Web/Windows) using ApprovalCard and verify Approve â†’ Calendar event creation end-to-end.
Task 4 â†’ Configure Render Deployment:
Add render.yaml, web/index.html config hook, and production CORS/redirect URIs in joshu-515708 before promoting to staging/prod.
