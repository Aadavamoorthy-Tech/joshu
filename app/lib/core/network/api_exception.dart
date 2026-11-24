/// Domain-level error categories mapped from HTTP, CORS, and network failures.
enum ApiErrorCode {
  /// 401: Joshu session invalid or expired → sign out
  unauthorized,

  /// 428/403: Google refresh token expired (7-day Testing cap)
  googleReconnectNeeded,

  /// 403: Incremental Gmail/Calendar scope not yet granted
  scopeUpgradeRequired,

  /// 403: Tenant isolation or backend policy violation
  forbidden,

  /// 400/422: Invalid request payload
  validationError,

  /// 409: Task already approved/rejected/expired
  conflict,

  /// 429: Retry after backoff
  rateLimited,

  /// Web CORS block or offline device
  corsOrNetworkBlocked,

  /// Request exceeded timeout
  timeout,

  /// 5xx backend error
  serverError,

  /// Unknown error
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

  /// Returns true if this error can be retried after backoff.
  bool get isRetryable =>
      code == ApiErrorCode.timeout ||
      code == ApiErrorCode.corsOrNetworkBlocked ||
      code == ApiErrorCode.serverError ||
      code == ApiErrorCode.rateLimited;

  @override
  String toString() => 'ApiException($code, status=$statusCode): $message';
}
