import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../auth/session_service.dart';
import 'api_exception.dart';

/// Centralized HTTP wrapper with Bearer injection, single-flight 401 refresh, and error mapping.
class ApiClient {
  static const _nonRefreshablePaths = <String>{
    '/auth/signin',
    '/auth/callback',
    '/auth/refresh',
    '/auth/logout',
  };

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

  /// Sends an authenticated POST request with optional body and idempotency key.
  Future<Map<String, dynamic>> postJson(
    String path, {
    Map<String, dynamic>? body,
    String? idempotencyKey,
  }) =>
      _send('POST', path, body: body, idempotencyKey: idempotencyKey);

  /// Sends an authenticated PATCH request.
  Future<Map<String, dynamic>> patchJson(
    String path, {
    Map<String, dynamic>? body,
    String? idempotencyKey,
  }) =>
      _send('PATCH', path, body: body, idempotencyKey: idempotencyKey);

  Future<Map<String, dynamic>> _send(
    String method,
    String path, {
    Map<String, String>? queryParameters,
    Map<String, dynamic>? body,
    String? idempotencyKey,
    bool isRetry = false,
  }) async {
    final normalizedBase = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    final uri = Uri.parse('$normalizedBase$path').replace(
      queryParameters: queryParameters,
    );
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

      final streamResponse = await _http.send(request).timeout(
            const Duration(seconds: 30),
            onTimeout: () => throw TimeoutException('Request timeout after 30s'),
          );

      final response = await http.Response.fromStream(streamResponse);
      stopwatch.stop();
      _logSafe(method, uri.path, response.statusCode, stopwatch.elapsedMilliseconds);

      if (response.statusCode >= 200 && response.statusCode < 300) {
        if (response.body.isEmpty) return <String, dynamic>{};
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) return decoded;
        return <String, dynamic>{'data': decoded};
      }

      // Single-flight 401 refresh for protected routes only.
      if (response.statusCode == 401 &&
          !isRetry &&
          !_nonRefreshablePaths.contains(path)) {
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

        await _sessionService.clearSession();
        onUnauthorizedSession();
        throw const ApiException(
          code: ApiErrorCode.unauthorized,
          message: 'Session expired. Please sign in again.',
          statusCode: 401,
        );
      }

      _throwApiException(response);
    } on TimeoutException {
      throw const ApiException(
        code: ApiErrorCode.timeout,
        message: 'Request timed out. Please check your connection.',
      );
    } on http.ClientException {
      throw ApiException(
        code: ApiErrorCode.corsOrNetworkBlocked,
        message: kIsWeb
            ? 'Unable to reach the server. Check your connection or backend CORS settings.'
            : 'Network unavailable. Please check your connection.',
      );
    } on ApiException {
      rethrow;
    } catch (_) {
      throw const ApiException(
        code: ApiErrorCode.unknown,
        message: 'An unexpected client error occurred.',
      );
    }
  }

  /// Rotates the opaque session token once across concurrent 401 failures.
  Future<bool> _attemptSingleFlightRefresh() async {
    if (_refreshInFlight != null) {
      return _refreshInFlight!.future;
    }

    final completer = Completer<bool>();
    _refreshInFlight = completer;

    try {
      final token = await _sessionService.getToken();
      if (token == null) {
        completer.complete(false);
        return false;
      }

      final normalizedBase = baseUrl.endsWith('/')
          ? baseUrl.substring(0, baseUrl.length - 1)
          : baseUrl;
      final uri = Uri.parse('$normalizedBase/auth/refresh');
      final response = await _http
          .post(
            uri,
            headers: {
              'Accept': 'application/json',
              'Authorization': 'Bearer $token',
            },
          )
          .timeout(const Duration(seconds: 15));

      if (response.statusCode == 200) {
        final data = jsonDecode(response.body) as Map<String, dynamic>;
        final newToken = data['session_token'] as String?;
        final expiresAtRaw = data['expires_at'] as String?;
        if (newToken != null && expiresAtRaw != null) {
          final existingScopes =
              _sessionService.cachedSession?.grantedScopes ?? const {'openid', 'email', 'profile'};
          await _sessionService.saveSessionData(
            token: newToken,
            expiresAt: DateTime.parse(expiresAtRaw),
            grantedScopes: existingScopes,
          );
          completer.complete(true);
          return true;
        }
      }

      completer.complete(false);
      return false;
    } catch (_) {
      completer.complete(false);
      return false;
    } finally {
      _refreshInFlight = null;
    }
  }

  /// Maps HTTP status codes and structured JSON errors to domain exceptions.
  Never _throwApiException(http.Response response) {
    final statusCode = response.statusCode;

    Map<String, dynamic>? body;
    try {
      final parsed = jsonDecode(response.body);
      if (parsed is Map<String, dynamic>) {
        body = parsed;
      }
    } catch (_) {
      body = null;
    }

    final message = (body?['message'] as String?) ??
        (body?['detail'] is String ? body!['detail'] as String : null) ??
        'Request failed with status $statusCode';
    final errorCode = (body?['error'] as String?) ?? (body?['code'] as String?);

    final apiErrorCode = switch (statusCode) {
      401 => ApiErrorCode.unauthorized,
      403 => errorCode == 'google_token_expired'
          ? ApiErrorCode.googleReconnectNeeded
          : errorCode == 'scope_upgrade_required'
              ? ApiErrorCode.scopeUpgradeRequired
              : ApiErrorCode.forbidden,
      400 || 422 => ApiErrorCode.validationError,
      409 => ApiErrorCode.conflict,
      429 => ApiErrorCode.rateLimited,
      >= 500 => ApiErrorCode.serverError,
      _ => ApiErrorCode.unknown,
    };

    if (apiErrorCode == ApiErrorCode.googleReconnectNeeded) {
      onGoogleReconnectRequired();
    }

    throw ApiException(
      code: apiErrorCode,
      statusCode: statusCode,
      message: message,
      serverRuleId: errorCode,
    );
  }

  /// Logs only non-sensitive metadata (never tokens, query params, or PII).
  void _logSafe(String method, String path, int status, int elapsedMs) {
    if (kDebugMode) {
      debugPrint('[ApiClient] $method $path -> $status (${elapsedMs}ms)');
    }
  }

  void close() => _http.close();
}
