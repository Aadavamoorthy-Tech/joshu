import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_web_auth_2/flutter_web_auth_2.dart';
import '../../core/models/user_profile.dart';
import '../../core/network/api_exception.dart';
import '../../providers/auth_provider.dart';
import '../../providers/core_providers.dart';

/// Signature matching `FlutterWebAuth2.authenticate` for dependency injection in tests.
typedef WebAuthAuthenticator = Future<String> Function({
  required String url,
  required String callbackUrlScheme,
});

/// OAuth 2.0 Sign-In Screen for Joshu (Personal AI Chief of Staff).
class SignInScreen extends ConsumerStatefulWidget {
  final WebAuthAuthenticator? authenticator;

  const SignInScreen({
    super.key,
    this.authenticator,
  });

  @override
  ConsumerState<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends ConsumerState<SignInScreen> {
  static const _nativeCallbackScheme = 'joshu';

  bool _isLoading = false;
  String? _errorMessage;

  Future<void> _handleGoogleSignIn() async {
    if (_isLoading) return;

    setState(() {
      _isLoading = true;
      _errorMessage = null;
    });

    try {
      final apiClient = ref.read(apiClientProvider);

      // On Web, flutter_web_auth_2 resolves the popup via a same-origin /auth.html relay.
      final signInBody = kIsWeb
          ? <String, dynamic>{'redirect_uri': '${Uri.base.origin}/auth.html'}
          : null;

      final signInResponse = await apiClient.postJson(
        '/auth/signin',
        body: signInBody,
      );

      final redirectUrl = signInResponse['redirect_url'];
      if (redirectUrl is! String || redirectUrl.isEmpty) {
        throw const FormatException('Server did not return an OAuth redirect URL.');
      }

      final parsedRedirect = Uri.tryParse(redirectUrl);
      if (parsedRedirect == null ||
          parsedRedirect.scheme != 'https' ||
          parsedRedirect.host != 'accounts.google.com') {
        throw const FormatException('Unexpected OAuth authorization host.');
      }

      final callbackScheme =
          kIsWeb ? Uri.base.scheme : _nativeCallbackScheme;

      final authenticate = widget.authenticator ??
          ({required String url, required String callbackUrlScheme}) =>
              FlutterWebAuth2.authenticate(
                url: url,
                callbackUrlScheme: callbackUrlScheme,
              );

      final callbackResult = await authenticate(
        url: redirectUrl,
        callbackUrlScheme: callbackScheme,
      );

      final callbackUri = Uri.parse(callbackResult);
      final oauthError = callbackUri.queryParameters['error'];
      if (oauthError != null && oauthError.isNotEmpty) {
        if (mounted) {
          setState(() {
            _errorMessage = oauthError == 'access_denied'
                ? 'Google sign-in was cancelled before granting access.'
                : 'Google sign-in failed ($oauthError). Please try again.';
          });
        }
        return;
      }

      final code = callbackUri.queryParameters['code'];
      final stateParam = callbackUri.queryParameters['state'];
      if (code == null ||
          code.isEmpty ||
          stateParam == null ||
          stateParam.isEmpty) {
        if (mounted) {
          setState(() {
            _errorMessage =
                'Sign-in callback was incomplete. Please try signing in again.';
          });
        }
        return;
      }

      final callbackResponse = await apiClient.getJson(
        '/auth/callback',
        queryParameters: {
          'code': code,
          'state': stateParam,
        },
      );

      final sessionToken = callbackResponse['session_token'];
      final expiresAtRaw = callbackResponse['expires_at'];
      final userJson = callbackResponse['user'];

      if (sessionToken is! String ||
          sessionToken.isEmpty ||
          expiresAtRaw is! String ||
          userJson is! Map<String, dynamic>) {
        throw const FormatException('Invalid session payload returned by server.');
      }

      final expiresAt = DateTime.parse(expiresAtRaw).toUtc();
      final userProfile = UserProfile.fromJson(userJson);

      await ref.read(authControllerProvider.notifier).completeSignIn(
            sessionToken: sessionToken,
            expiresAt: expiresAt,
            user: userProfile,
          );

      if (mounted && ModalRoute.of(context)?.settings.name == '/signin') {
        await Navigator.of(context).pushReplacementNamed('/home');
      }
    } on PlatformException catch (e) {
      if (!mounted) return;
      final isCancelled = e.code.toUpperCase().contains('CANCEL');
      setState(() {
        _errorMessage = isCancelled
            ? 'Sign-in was cancelled. You can try again whenever you are ready.'
            : 'Unable to open Google sign-in window. Please try again.';
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
      });
    } on FormatException catch (e) {
      if (!mounted) return;
      setState(() {
        _errorMessage = e.message;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _errorMessage =
            'Sign-in could not be completed. Please verify your connection and try again.';
      });
    } finally {
      if (mounted) {
        setState(() {
          _isLoading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final authError = ref.watch(authControllerProvider).valueOrNull?.errorMessage;
    final visibleError = _errorMessage ?? authError;

    return Scaffold(
      backgroundColor: colorScheme.surface,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Card(
                elevation: 0,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(20),
                  side: BorderSide(
                    color: colorScheme.outlineVariant,
                  ),
                ),
                child: Padding(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 32,
                    vertical: 40,
                  ),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      Center(
                        child: Container(
                          width: 56,
                          height: 56,
                          decoration: BoxDecoration(
                            color: colorScheme.primaryContainer,
                            borderRadius: BorderRadius.circular(14),
                          ),
                          child: Icon(
                            Icons.verified_user_outlined,
                            size: 28,
                            color: colorScheme.onPrimaryContainer,
                          ),
                        ),
                      ),
                      const SizedBox(height: 24),
                      Text(
                        'Joshu',
                        style: theme.textTheme.headlineMedium?.copyWith(
                          fontWeight: FontWeight.w700,
                          letterSpacing: -0.5,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 6),
                      Text(
                        'Personal AI Chief of Staff',
                        style: theme.textTheme.titleSmall?.copyWith(
                          color: colorScheme.primary,
                          fontWeight: FontWeight.w600,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Sign in with your Google account to review meeting invites, bills, and administrative approvals with full human-in-the-loop control.',
                        style: theme.textTheme.bodyMedium?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                          height: 1.5,
                        ),
                        textAlign: TextAlign.center,
                      ),
                      if (visibleError != null) ...[
                        const SizedBox(height: 24),
                        Container(
                          padding: const EdgeInsets.all(14),
                          decoration: BoxDecoration(
                            color: colorScheme.errorContainer,
                            borderRadius: BorderRadius.circular(12),
                          ),
                          child: Row(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Icon(
                                Icons.error_outline,
                                size: 20,
                                color: colorScheme.onErrorContainer,
                              ),
                              const SizedBox(width: 10),
                              Expanded(
                                child: Text(
                                  visibleError,
                                  style: theme.textTheme.bodySmall?.copyWith(
                                    color: colorScheme.onErrorContainer,
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                      const SizedBox(height: 28),
                      SizedBox(
                        height: 48,
                        child: FilledButton.icon(
                          key: const Key('google_sign_in_button'),
                          onPressed: _isLoading ? null : _handleGoogleSignIn,
                          icon: _isLoading
                              ? SizedBox(
                                  width: 18,
                                  height: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                    color: colorScheme.onPrimary,
                                  ),
                                )
                              : const Icon(Icons.login_rounded),
                          label: Text(
                            _isLoading ? 'Signing in...' : 'Sign in with Google',
                          ),
                        ),
                      ),
                      const SizedBox(height: 20),
                      Text(
                        'Your Google credentials stay protected on the server. Only an encrypted session token is stored on this device.',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                        ),
                        textAlign: TextAlign.center,
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
