/// Web implementation using `package:web` (`window.localStorage`) behind conditional import.
/// Note: For higher XSS resistance in production, migrate Web sessions to FastAPI
/// `HttpOnly; Secure; SameSite=Lax` cookies while keeping this adapter for native clients.
library;

import 'package:web/web.dart' as web;
import 'token_storage_adapter.dart';

class WebTokenStorageAdapter implements TokenStorageAdapter {
  @override
  Future<String?> read(String key) async {
    try {
      return web.window.localStorage[key];
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> write(String key, String value) async {
    web.window.localStorage[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    web.window.localStorage.removeItem(key);
  }
}

// Stub for compatibility with platform-specific conditional imports
// This is never instantiated on web platforms
class NativeSecureStorageAdapter implements TokenStorageAdapter {
  NativeSecureStorageAdapter({dynamic storage});

  @override
  Future<String?> read(String key) async => null;

  @override
  Future<void> write(String key, String value) async {}

  @override
  Future<void> delete(String key) async {}
}
