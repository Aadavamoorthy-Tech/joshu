import 'dart:convert';
import '../models/auth_session.dart';
import 'token_storage_adapter.dart';

/// Coordinates opaque session persistence, expiry buffer checks, and logout cleanup.
class SessionService {
  static const _storageKey = 'joshu_auth_session_v1';

  final TokenStorageAdapter _storage;
  AuthSession? _cached;

  SessionService({required TokenStorageAdapter storage}) : _storage = storage;

  /// Restores and validates an existing session on app startup.
  /// Clears storage and returns null if missing, corrupted, or expired.
  Future<AuthSession?> restoreSession() async {
    try {
      final raw = await _storage.read(_storageKey);
      if (raw == null || raw.isEmpty) return null;

      final decoded = jsonDecode(raw);
      if (decoded is! Map<String, dynamic>) {
        await clearSession();
        return null;
      }

      final session = AuthSession.fromJson(decoded);
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

  /// Returns current opaque bearer token from memory or secure storage.
  Future<String?> getToken() async {
    if (_cached != null && !_cached!.isExpiredOrNearExpiry) {
      return _cached!.sessionToken;
    }

    final restored = await restoreSession();
    return restored?.sessionToken;
  }

  /// Persists an [AuthSession] atomically to memory and platform storage.
  Future<void> saveSession(AuthSession session) async {
    _cached = session;
    await _storage.write(_storageKey, jsonEncode(session.toJson()));
  }

  /// Convenience helper to persist session fields returned by `/auth/callback` or `/auth/refresh`.
  Future<AuthSession> saveSessionData({
    required String token,
    required DateTime expiresAt,
    Set<String> grantedScopes = const {'openid', 'email', 'profile'},
    bool googleReconnectRequired = false,
  }) async {
    final session = AuthSession(
      sessionToken: token,
      expiresAt: expiresAt.toUtc(),
      grantedScopes: grantedScopes,
      googleReconnectRequired: googleReconnectRequired,
    );
    await saveSession(session);
    return session;
  }

  /// Validates or rotates the current session via a backend callback.
  /// Clears local storage and returns null if the backend rejects the session.
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

  /// Clears in-memory and persisted credentials on logout.
  Future<void> clearSession() async {
    _cached = null;
    await _storage.delete(_storageKey);
  }

  /// Returns the cached session without disk I/O.
  AuthSession? get cachedSession => _cached;
}
