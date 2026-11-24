import 'dart:convert';
import '../models/auth_session.dart';
import 'token_storage_adapter.dart';

/// Coordinates OAuth launch, session persistence, sliding refresh, and logout.
class SessionService {
  static const _storageKey = 'joshu_auth_session_v1';

  final TokenStorageAdapter _storage;
  AuthSession? _cached;

  SessionService({required this._storage});

  /// Restores and validates an existing session on app startup.
  /// Clears storage and returns null if missing, corrupted, or expired.
  Future<AuthSession?> restoreSession() async {
    try {
      final raw = await _storage.read(_storageKey);
      if (raw == null) return null;

      final session = AuthSession.fromJson(jsonDecode(raw));

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

  /// Returns current bearer token from memory or secure storage.
  Future<String?> getToken() async {
    if (_cached != null && !_cached!.isExpiredOrNearExpiry) {
      return _cached!.sessionToken;
    }

    final restored = await restoreSession();
    return restored?.sessionToken;
  }

  /// Calls POST /oauth/token to validate and slide the 30-day session.
  /// Returns null if the backend rejects the session (401).
  /// remoteValidate: Callback to validate token with backend.
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
    await _storage.write(_storageKey, jsonEncode(session.toJson()));
  }

  /// Clears in-memory and persisted credentials on logout.
  Future<void> clearSession() async {
    _cached = null;
    await _storage.delete(_storageKey);
  }

  /// Returns the cached session without disk I/O.
  /// Used for quick checks during the app lifecycle.
  AuthSession? get cachedSession => _cached;
}
