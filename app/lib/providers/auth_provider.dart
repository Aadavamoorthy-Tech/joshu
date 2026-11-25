import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models/user_profile.dart';
import '../core/network/api_exception.dart';
import 'core_providers.dart';

/// Authentication state machine.
enum AuthStatus { loading, signedOut, signedIn }

/// Immutable authentication state exposed to the widget tree.
class AuthState {
  final AuthStatus status;
  final String? sessionToken;
  final UserProfile? user;
  final DateTime? expiresAt;
  final Set<String> grantedScopes;
  final bool googleReconnectRequired;
  final String? errorMessage;

  const AuthState({
    required this.status,
    this.sessionToken,
    this.user,
    this.expiresAt,
    this.grantedScopes = const {},
    this.googleReconnectRequired = false,
    this.errorMessage,
  });

  /// Convenience flag indicating an active authenticated session.
  bool get isAuthenticated =>
      status == AuthStatus.signedIn && sessionToken != null && user != null;

  /// Returns true if basic email/profile scopes are granted.
  bool get hasBasicScopes =>
      grantedScopes.contains('email') && grantedScopes.contains('profile');

  /// Returns true if Gmail and Calendar scopes are granted.
  bool get hasWorkspaceScopes =>
      grantedScopes.contains('https://www.googleapis.com/auth/gmail.readonly') &&
      grantedScopes.contains('https://www.googleapis.com/auth/calendar.events');

  AuthState copyWith({
    AuthStatus? status,
    String? sessionToken,
    UserProfile? user,
    DateTime? expiresAt,
    Set<String>? grantedScopes,
    bool? googleReconnectRequired,
    String? errorMessage,
  }) =>
      AuthState(
        status: status ?? this.status,
        sessionToken: sessionToken ?? this.sessionToken,
        user: user ?? this.user,
        expiresAt: expiresAt ?? this.expiresAt,
        grantedScopes: grantedScopes ?? this.grantedScopes,
        googleReconnectRequired:
            googleReconnectRequired ?? this.googleReconnectRequired,
        errorMessage: errorMessage,
      );
}

/// Manages Google OAuth sign-in completion, startup session validation/rotation, and logout.
class AuthController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async {
    final sessionService = ref.read(sessionServiceProvider);
    final session = await sessionService.restoreSession();

    if (session == null) {
      return const AuthState(status: AuthStatus.signedOut);
    }

    // Validate and rotate the cached session token with FastAPI on startup.
    try {
      final apiClient = ref.read(apiClientProvider);
      final refreshJson = await apiClient.postJson('/auth/refresh');

      final rotatedToken = refreshJson['session_token'] as String?;
      final expiresAtRaw = refreshJson['expires_at'] as String?;
      final userMap = refreshJson['user'];

      if (rotatedToken == null ||
          expiresAtRaw == null ||
          userMap is! Map<String, dynamic>) {
        await sessionService.clearSession();
        return const AuthState(
          status: AuthStatus.signedOut,
          errorMessage: 'Session validation failed. Please sign in again.',
        );
      }

      final expiresAt = DateTime.parse(expiresAtRaw).toUtc();
      final userProfile = UserProfile.fromJson(userMap);

      await sessionService.saveSessionData(
        token: rotatedToken,
        expiresAt: expiresAt,
        grantedScopes: session.grantedScopes,
        googleReconnectRequired: session.googleReconnectRequired,
      );

      return AuthState(
        status: AuthStatus.signedIn,
        sessionToken: rotatedToken,
        user: userProfile,
        expiresAt: expiresAt,
        grantedScopes: session.grantedScopes,
        googleReconnectRequired: session.googleReconnectRequired,
      );
    } on ApiException catch (e) {
      await sessionService.clearSession();
      return AuthState(
        status: AuthStatus.signedOut,
        errorMessage: 'Session expired: ${e.message}',
      );
    } catch (_) {
      await sessionService.clearSession();
      return const AuthState(
        status: AuthStatus.signedOut,
        errorMessage: 'Unable to restore session. Please sign in again.',
      );
    }
  }

  /// Finalizes sign-in after `/auth/callback` returns a fresh session token and user profile.
  Future<void> completeSignIn({
    required String sessionToken,
    required DateTime expiresAt,
    required UserProfile user,
    Set<String> grantedScopes = const {'openid', 'email', 'profile'},
  }) async {
    final sessionService = ref.read(sessionServiceProvider);
    final utcExpiry = expiresAt.toUtc();

    await sessionService.saveSessionData(
      token: sessionToken,
      expiresAt: utcExpiry,
      grantedScopes: grantedScopes,
    );

    state = AsyncValue.data(
      AuthState(
        status: AuthStatus.signedIn,
        sessionToken: sessionToken,
        user: user,
        expiresAt: utcExpiry,
        grantedScopes: grantedScopes,
      ),
    );
  }

  /// Validates an existing opaque session token via `/auth/refresh` and updates auth state.
  Future<void> login(String sessionToken) async {
    state = const AsyncValue.loading();
    final sessionService = ref.read(sessionServiceProvider);

    try {
      await sessionService.saveSessionData(
        token: sessionToken,
        expiresAt: DateTime.now().toUtc().add(const Duration(days: 30)),
      );

      final apiClient = ref.read(apiClientProvider);
      final refreshJson = await apiClient.postJson('/auth/refresh');
      final rotatedToken = refreshJson['session_token'] as String;
      final expiresAt = DateTime.parse(refreshJson['expires_at'] as String).toUtc();
      final user = UserProfile.fromJson(
        refreshJson['user'] as Map<String, dynamic>,
      );

      await completeSignIn(
        sessionToken: rotatedToken,
        expiresAt: expiresAt,
        user: user,
      );
    } on ApiException catch (e) {
      await sessionService.clearSession();
      state = AsyncValue.data(
        AuthState(
          status: AuthStatus.signedOut,
          errorMessage: e.message,
        ),
      );
    } catch (_) {
      await sessionService.clearSession();
      state = const AsyncValue.data(
        AuthState(
          status: AuthStatus.signedOut,
          errorMessage: 'Sign-in failed. Please try again.',
        ),
      );
    }
  }

  /// Triggered by ApiClient when backend reports 7-day Testing token expiry.
  void markGoogleReconnectRequired() {
    state.whenData((authState) {
      state = AsyncValue.data(
        authState.copyWith(googleReconnectRequired: true),
      );
    });
  }

  /// Clears local auth state immediately when ApiClient encounters an unrecoverable 401.
  void forceSignedOut([String? reason]) {
    state = AsyncValue.data(
      AuthState(
        status: AuthStatus.signedOut,
        errorMessage: reason,
      ),
    );
  }

  /// Revokes the active session on the backend and wipes local storage.
  Future<void> logout() async {
    final sessionService = ref.read(sessionServiceProvider);
    final apiClient = ref.read(apiClientProvider);

    try {
      final token = await sessionService.getToken();
      if (token != null) {
        await apiClient.postJson('/auth/logout');
      }
    } catch (_) {
      // Always complete local logout even if network is unavailable or session was already revoked.
    } finally {
      await sessionService.clearSession();
      state = const AsyncValue.data(AuthState(status: AuthStatus.signedOut));
    }
  }

  /// Backwards-compatible alias for [logout].
  Future<void> signOut() => logout();
}

/// Riverpod provider for auth state management.
final authControllerProvider = AsyncNotifierProvider<AuthController, AuthState>(
  AuthController.new,
);
