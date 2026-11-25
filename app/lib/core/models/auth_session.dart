/// OAuth session issued by FastAPI, authenticated with 30-day TTL.
class AuthSession {
  /// Opaque bearer token issued by FastAPI.
  final String sessionToken;

  /// Expiration timestamp in UTC from FastAPI sessions table.
  final DateTime expiresAt;

  /// Granted Google scopes currently active on the backend.
  final Set<String> grantedScopes;

  /// True when backend Google refresh token hit invalid_grant (7-day Testing cap).
  final bool googleReconnectRequired;

  const AuthSession({
    required this.sessionToken,
    required this.expiresAt,
    required this.grantedScopes,
    this.googleReconnectRequired = false,
  });

  /// Returns true if the local session is expired or within 5-minute safety buffer.
  bool get isExpiredOrNearExpiry =>
      DateTime.now().toUtc().isAfter(expiresAt.subtract(const Duration(minutes: 5)));

  /// JSON encoding for secure storage.
  Map<String, dynamic> toJson() => {
    'sessionToken': sessionToken,
    'expiresAt': expiresAt.toIso8601String(),
    'grantedScopes': grantedScopes.toList(),
    'googleReconnectRequired': googleReconnectRequired,
  };

  /// JSON decoding from secure storage.
  factory AuthSession.fromJson(Map<String, dynamic> json) => AuthSession(
    sessionToken: json['sessionToken'] as String,
    expiresAt: DateTime.parse(json['expiresAt'] as String).toUtc(),
    grantedScopes: Set<String>.from(json['grantedScopes'] as List<dynamic>? ?? []),
    googleReconnectRequired: json['googleReconnectRequired'] as bool? ?? false,
  );
}
