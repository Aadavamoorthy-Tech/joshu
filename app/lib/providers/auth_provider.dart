import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models/user_profile.dart';
import '../core/network/api_exception.dart';
import 'core_providers.dart';

/// Authentication state machine.
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

  /// Returns true if basic email/profile scopes are granted.
  bool get hasBasicScopes => grantedScopes.contains('email') && grantedScopes.contains('profile');

  /// Returns true if Gmail and Calendar scopes are granted.
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
class AuthController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async {
    // Bootstrap: Try to restore previous session on app start.
    final sessionService = ref.read(sessionServiceProvider);
    final session = await sessionService.restoreSession();

    if (session == null) {
      return const AuthState(status: AuthStatus.signedOut);
    }

    // Validate session with backend.
    try {
      final apiClient = ref.read(apiClientProvider);
      final profileJson = await apiClient.postJson('/oauth/token');
      final userProfile = UserProfile.fromJson(profileJson);

      return AuthState(
        status: AuthStatus.signedIn,
        user: userProfile,
        grantedScopes: session.grantedScopes,
        googleReconnectRequired: session.googleReconnectRequired,
      );
    } on ApiException catch (e) {
      // Session token is invalid, clear and require re-signin.
      await sessionService.clearSession();
      return AuthState(
        status: AuthStatus.signedOut,
        errorMessage: 'Session expired: ${e.message}',
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

  /// Signs out locally and clears session.
  Future<void> signOut() async {
    final sessionService = ref.read(sessionServiceProvider);
    await sessionService.clearSession();

    state = const AsyncValue.data(AuthState(status: AuthStatus.signedOut));
  }
}

/// Riverpod provider for auth state management.
final authControllerProvider = AsyncNotifierProvider<AuthController, AuthState>(
  AuthController.new,
);
