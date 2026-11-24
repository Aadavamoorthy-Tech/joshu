import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/auth/session_service.dart';
import '../core/auth/token_storage_adapter.dart';
import '../core/auth/token_storage_web.dart';
import '../core/config/app_config.dart';
import '../core/network/api_client.dart';

// Only import native on non-web platforms using conditional import
import '../core/auth/token_storage_native.dart'
    if (dart.library.html) '../core/auth/token_storage_web.dart' as platform_storage;

/// Global app configuration loaded from environment.
final appConfigProvider = Provider<AppConfig>((ref) {
  return AppConfig.fromEnvironment();
});

/// Platform-specific token storage adapter.
final tokenStorageAdapterProvider = Provider<TokenStorageAdapter>((ref) {
  if (kIsWeb) {
    return WebTokenStorageAdapter();
  }
  // On native platforms, NativeSecureStorageAdapter is available via platform_storage
  return platform_storage.NativeSecureStorageAdapter();
});

/// Session service for managing auth session lifecycle.
final sessionServiceProvider = Provider<SessionService>((ref) {
  final adapter = ref.watch(tokenStorageAdapterProvider);
  return SessionService(storage: adapter);
});

/// HTTP client for authenticated API calls.
final apiClientProvider = Provider<ApiClient>((ref) {
  final config = ref.watch(appConfigProvider);
  final sessionService = ref.watch(sessionServiceProvider);

  return ApiClient(
    baseUrl: config.apiBaseUrl,
    sessionService: sessionService,
    onUnauthorizedSession: () {
      // TODO: Navigate to sign-in screen
      // In production, replace with logging framework
    },
    onGoogleReconnectRequired: () {
      // TODO: Show reconnect banner
      // In production, replace with logging framework
    },
  );
});
