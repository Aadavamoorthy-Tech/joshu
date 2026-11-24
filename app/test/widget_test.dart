import 'dart:convert';
import 'package:chief_of_staff/core/auth/token_storage_adapter.dart';
import 'package:chief_of_staff/core/models/auth_session.dart';
import 'package:chief_of_staff/core/network/api_client.dart';
import 'package:chief_of_staff/main.dart';
import 'package:chief_of_staff/presentation/screens/sign_in_screen.dart';
import 'package:chief_of_staff/providers/auth_provider.dart';
import 'package:chief_of_staff/providers/core_providers.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

class _InMemoryTokenStorageAdapter implements TokenStorageAdapter {
  final Map<String, String> _store = <String, String>{};

  @override
  Future<String?> read(String key) async => _store[key];

  @override
  Future<void> write(String key, String value) async {
    _store[key] = value;
  }

  @override
  Future<void> delete(String key) async {
    _store.remove(key);
  }

  bool get isEmpty => _store.isEmpty;
}

void main() {
  testWidgets('Shows SignInScreen with Google button when signed out', (
    tester,
  ) async {
    final memoryStorage = _InMemoryTokenStorageAdapter();

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageAdapterProvider.overrideWithValue(memoryStorage),
        ],
        child: const ChiefOfStaffApp(),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.byType(SignInScreen), findsOneWidget);
    expect(find.byKey(const Key('google_sign_in_button')), findsOneWidget);
    expect(find.text('Sign in with Google'), findsOneWidget);
  });

  testWidgets('Restores valid session on startup and signs out cleanly', (
    tester,
  ) async {
    final memoryStorage = _InMemoryTokenStorageAdapter();
    final futureExpiry = DateTime.now().toUtc().add(const Duration(days: 20));
    await memoryStorage.write(
      'joshu_auth_session_v1',
      jsonEncode(
        AuthSession(
          sessionToken: 'initial-session-uuid',
          expiresAt: futureExpiry,
          grantedScopes: const {'openid', 'email', 'profile'},
        ).toJson(),
      ),
    );

    var logoutCalled = false;
    final mockHttp = MockClient((request) async {
      if (request.url.path == '/auth/refresh' && request.method == 'POST') {
        expect(
          request.headers['Authorization'],
          equals('Bearer initial-session-uuid'),
        );
        return http.Response(
          jsonEncode({
            'session_token': 'rotated-session-uuid',
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(days: 30))
                .toIso8601String(),
            'user': {
              'email': 'alex@company.com',
              'name': 'Alex Rivera',
              'picture_url': null,
            },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      if (request.url.path == '/auth/logout' && request.method == 'POST') {
        logoutCalled = true;
        expect(
          request.headers['Authorization'],
          equals('Bearer rotated-session-uuid'),
        );
        return http.Response(
          jsonEncode({'message': 'Logged out successfully'}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      return http.Response('Not found', 404);
    });

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageAdapterProvider.overrideWithValue(memoryStorage),
          apiClientProvider.overrideWith((ref) {
            final sessionService = ref.watch(sessionServiceProvider);
            return ApiClient(
              baseUrl: 'http://localhost:8000',
              sessionService: sessionService,
              httpClient: mockHttp,
              onUnauthorizedSession: () {
                ref.read(authControllerProvider.notifier).forceSignedOut();
              },
              onGoogleReconnectRequired: () {
                ref
                    .read(authControllerProvider.notifier)
                    .markGoogleReconnectRequired();
              },
            );
          }),
        ],
        child: const ChiefOfStaffApp(),
      ),
    );
    await tester.pumpAndSettle();

    // Authenticated InboxScreen renders with restored user profile.
    expect(find.byType(InboxScreen), findsOneWidget);
    expect(find.text('alex@company.com'), findsOneWidget);
    expect(find.text('Welcome back, Alex Rivera'), findsOneWidget);

    // Tapping Sign out revokes backend session and returns to SignInScreen.
    await tester.tap(find.byKey(const Key('sign_out_button')));
    await tester.pumpAndSettle();

    expect(logoutCalled, isTrue);
    expect(memoryStorage.isEmpty, isTrue);
    expect(find.byType(SignInScreen), findsOneWidget);
  });

  testWidgets('Completes full OAuth sign-in flow via SignInScreen', (
    tester,
  ) async {
    final memoryStorage = _InMemoryTokenStorageAdapter();

    final mockHttp = MockClient((request) async {
      if (request.url.path == '/auth/signin' && request.method == 'POST') {
        return http.Response(
          jsonEncode({
            'redirect_url':
                'https://accounts.google.com/o/oauth2/v2/auth?state=test-csrf-state&scope=openid+email+profile',
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      if (request.url.path == '/auth/callback' && request.method == 'GET') {
        expect(request.url.queryParameters['code'], equals('test-auth-code'));
        expect(request.url.queryParameters['state'], equals('test-csrf-state'));
        return http.Response(
          jsonEncode({
            'session_token': 'fresh-session-uuid',
            'expires_at': DateTime.now()
                .toUtc()
                .add(const Duration(days: 30))
                .toIso8601String(),
            'user': {
              'email': 'jordan@company.com',
              'name': 'Jordan Lee',
              'picture_url': null,
            },
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      return http.Response('Not found', 404);
    });

    await tester.pumpWidget(
      ProviderScope(
        overrides: [
          tokenStorageAdapterProvider.overrideWithValue(memoryStorage),
          apiClientProvider.overrideWith((ref) {
            final sessionService = ref.watch(sessionServiceProvider);
            return ApiClient(
              baseUrl: 'http://localhost:8000',
              sessionService: sessionService,
              httpClient: mockHttp,
              onUnauthorizedSession: () {},
              onGoogleReconnectRequired: () {},
            );
          }),
        ],
        child: MaterialApp(
          home: Consumer(
            builder: (context, ref, _) {
              final auth = ref.watch(authControllerProvider).valueOrNull;
              if (auth != null && auth.isAuthenticated) {
                return InboxScreen(user: auth.user!);
              }
              return SignInScreen(
                authenticator: ({
                  required String url,
                  required String callbackUrlScheme,
                }) async {
                  return 'joshu://callback?code=test-auth-code&state=test-csrf-state';
                },
              );
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('google_sign_in_button')));
    await tester.pumpAndSettle();

    expect(find.byType(InboxScreen), findsOneWidget);
    expect(find.text('jordan@company.com'), findsOneWidget);
    expect(memoryStorage.isEmpty, isFalse);
  });
}
