import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import '../auth/session_service.dart';
import 'api_exception.dart';

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
    required this._sessionService,
    required this.onUnauthorizedSession,
    required this.onGoogleReconnectRequired,
    http.Client? httpClient,
  }) : _http = httpClient ?? http.Client();

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

      final streamResponse = await _http.send(request).timeout(
        const Duration(seconds: 30),
        onTimeout: () => throw TimeoutException('Request timeout after 30s'),
      );

      final response = await http.Response.fromStream(streamResponse);
      _logSafe(method, path, response.statusCode, stopwatch.elapsedMilliseconds);

      if (response.statusCode == 200 || response.statusCode == 201) {
        return jsonDecode(response.body) as Map<String, dynamic>;
      }

      /// Handle 401 (unauthorized session) with single-flight refresh
      if (response.statusCode == 401 && !isRetry && path != '/oauth/token') {
        _refreshInFlight ??= Completer<bool>();

        final canRetry = await _refreshInFlight!.future;
        _refreshInFlight = null;

        if (canRetry) {
          return await _send(
            method,
            path,
            queryParameters: queryParameters,
            body: body,
            idempotencyKey: idempotencyKey,
            isRetry: true,
          );
        }

        onUnauthorizedSession();
        throw ApiException(
          code: ApiErrorCode.unauthorized,
          message: 'Session expired. Please sign in again.',
          statusCode: 401,
        );
      }

      /// Map HTTP errors to domain errors
      _throwApiException(response);
    } on TimeoutException {
      throw ApiException(
        code: ApiErrorCode.timeout,
        message: 'Request timed out. Please check your connection.',
      );
    } on http.ClientException catch (e) {
      /// Browser CORS blocks appear as ClientException on web
      throw ApiException(
        code: ApiErrorCode.corsOrNetworkBlocked,
        message: 'Network error or CORS blocked. ${e.message}',
      );
    } on ApiException {
      rethrow;
    } catch (e) {
      throw ApiException(
        code: ApiErrorCode.unknown,
        message: 'Unexpected error: $e',
      );
    }
  }

  /// Maps HTTP status codes and backend error responses to domain exceptions.
  /// This method always throws and never returns.
  Never _throwApiException(http.Response response) {
    final statusCode = response.statusCode;

    Map<String, dynamic>? body;
    try {
      body = jsonDecode(response.body) as Map<String, dynamic>?;
    } catch (_) {
      body = null;
    }

    final detail = body?['detail'] as String? ?? 'Unknown error';
    final code = body?['code'] as String?;

    final apiErrorCode = switch (statusCode) {
      401 => ApiErrorCode.unauthorized,
      403 => code == 'google_token_expired'
          ? ApiErrorCode.googleReconnectNeeded
          : code == 'scope_upgrade_required'
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
      message: detail,
      serverRuleId: code,
    );
  }

  /// Logs only non-sensitive metadata (never tokens, query params, or PII bodies).
  void _logSafe(String method, String path, int status, int elapsedMs) {
    if (kDebugMode) {
      debugPrint('[ApiClient] $method $path -> $status (${elapsedMs}ms)');
    }
  }

  void close() => _http.close();
}
