import 'dart:convert';
import 'package:chief_of_staff/core/auth/token_storage_adapter.dart';
import 'package:chief_of_staff/core/models/auth_session.dart';
import 'package:chief_of_staff/core/models/user_profile.dart';
import 'package:chief_of_staff/core/network/api_client.dart';
import 'package:chief_of_staff/main.dart';
import 'package:chief_of_staff/presentation/screens/sign_in_screen.dart';
import 'package:chief_of_staff/presentation/widgets/reject_confirmation_dialog.dart';
import 'package:chief_of_staff/presentation/widgets/task_card.dart';
import 'package:chief_of_staff/presentation/widgets/task_detail_modal.dart';
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

Map<String, dynamic> _sampleTaskJson({
  required String id,
  required String title,
  String status = 'pending',
  String? rejectionReason,
}) =>
    {
      'id': id,
      'user_id': 1,
      'title': title,
      'description': 'Quarterly agenda and milestone review.',
      'scheduled_for': '2026-11-25T15:00:00Z',
      'source': 'calendar',
      'status': status,
      'organizer': 'manager@company.com',
      'attendees': ['manager@company.com', 'colleague@company.com'],
      'calendar_event_link': 'https://meet.google.com/abc-defg-hij',
      'raw_data': {
        'organizer': 'manager@company.com',
        'attendees': ['manager@company.com', 'colleague@company.com'],
        'calendar_event_link': 'https://meet.google.com/abc-defg-hij',
      },
      'created_at': '2026-11-24T12:00:00Z',
      'updated_at': '2026-11-24T12:00:00Z',
      'approved_at': status == 'approved' ? '2026-11-24T14:00:00Z' : null,
      'rejected_at': status == 'rejected' ? '2026-11-24T14:00:00Z' : null,
      'rejection_reason': rejectionReason,
      'approved_by_user': status == 'approved',
    };

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

      if (request.url.path == '/tasks' && request.method == 'GET') {
        return http.Response(
          jsonEncode({'tasks': [], 'total': 0}),
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

    expect(find.byType(InboxScreen), findsOneWidget);
    expect(find.text('alex@company.com'), findsOneWidget);
    expect(find.text('Welcome back, Alex Rivera'), findsOneWidget);

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

      if (request.url.path == '/tasks' && request.method == 'GET') {
        return http.Response(
          jsonEncode({'tasks': [], 'total': 0}),
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

  testWidgets(
    'Phase 3: approves, rejects with reason, filters, and opens task details modal',
    (tester) async {
      final memoryStorage = _InMemoryTokenStorageAdapter();
      var approvedCalled = false;
      String? capturedRejectReason;

      final mockHttp = MockClient((request) async {
        if (request.url.path == '/tasks' && request.method == 'GET') {
          return http.Response(
            jsonEncode({
              'tasks': [
                _sampleTaskJson(id: 'task-1', title: 'Team Standup'),
                _sampleTaskJson(id: 'task-2', title: 'Project Review Meeting'),
              ],
              'total': 2,
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path == '/tasks/task-1/approve' &&
            request.method == 'POST') {
          approvedCalled = true;
          return http.Response(
            jsonEncode({
              'task_id': 'task-1',
              'status': 'approved',
              'approved_at': '2026-11-24T16:15:00Z',
              'task': _sampleTaskJson(
                id: 'task-1',
                title: 'Team Standup',
                status: 'approved',
              ),
              'message': 'Task approved successfully',
            }),
            200,
            headers: {'content-type': 'application/json'},
          );
        }

        if (request.url.path == '/tasks/task-2/reject' &&
            request.method == 'POST') {
          final body = jsonDecode(request.body) as Map<String, dynamic>;
          capturedRejectReason = body['reason'] as String?;
          return http.Response(
            jsonEncode({
              'task_id': 'task-2',
              'status': 'rejected',
              'rejected_at': '2026-11-24T16:20:00Z',
              'rejection_reason': capturedRejectReason,
              'task': _sampleTaskJson(
                id: 'task-2',
                title: 'Project Review Meeting',
                status: 'rejected',
                rejectionReason: capturedRejectReason,
              ),
              'message': 'Task rejected successfully',
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
          child: const MaterialApp(
            home: InboxScreen(
              user: UserProfile(email: 'founder@joshu.app', name: 'Founder'),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Both task cards load on mount.
      expect(find.byType(TaskCard), findsNWidgets(2));
      expect(find.text('Team Standup'), findsOneWidget);
      expect(find.text('Project Review Meeting'), findsOneWidget);

      // Open Details modal for Task 1 and verify full attendees list.
      await tester.tap(find.byKey(const Key('details_button_task-1')));
      await tester.pumpAndSettle();
      expect(find.byType(TaskDetailModal), findsOneWidget);
      expect(find.text('colleague@company.com'), findsOneWidget);

      // Close modal, then click Approve on Task 1.
      await tester.tap(find.text('Close'));
      await tester.pumpAndSettle();

      await tester.tap(find.byKey(const Key('approve_button_task-1')));
      await tester.pumpAndSettle();
      expect(approvedCalled, isTrue);
      expect(find.text('Task approved!'), findsOneWidget);

      // Click Reject on Task 2 -> confirmation dialog -> enter reason -> confirm.
      await tester.tap(find.byKey(const Key('reject_button_task-2')));
      await tester.pumpAndSettle();
      expect(find.byType(RejectConfirmationDialog), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('reject_reason_field')),
        'Already scheduled',
      );
      await tester.tap(find.byKey(const Key('reject_dialog_confirm')));
      await tester.pumpAndSettle();

      expect(capturedRejectReason, equals('Already scheduled'));
      expect(find.text('Rejection reason: Already scheduled'), findsOneWidget);

      // Filter by Approved shows only Team Standup.
      await tester.tap(find.byKey(const Key('filter_approved')));
      await tester.pumpAndSettle();
      expect(find.text('Team Standup'), findsOneWidget);
      expect(find.text('Project Review Meeting'), findsNothing);

      // Filter by Pending shows "All tasks reviewed!".
      await tester.tap(find.byKey(const Key('filter_pending')));
      await tester.pumpAndSettle();
      expect(find.text('All tasks reviewed!'), findsOneWidget);
    },
  );

  testWidgets('Phase 3: rolls back optimistic approval when backend fails', (
    tester,
  ) async {
    final memoryStorage = _InMemoryTokenStorageAdapter();

    final mockHttp = MockClient((request) async {
      if (request.url.path == '/tasks' && request.method == 'GET') {
        return http.Response(
          jsonEncode({
            'tasks': [_sampleTaskJson(id: 'task-err', title: 'Board Sync')],
            'total': 1,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }

      if (request.url.path == '/tasks/task-err/approve' &&
          request.method == 'POST') {
        return http.Response(
          jsonEncode({
            'error': 'task_update_failed',
            'message': 'Database unavailable',
            'status': 500,
          }),
          500,
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
        child: const MaterialApp(
          home: InboxScreen(
            user: UserProfile(email: 'founder@joshu.app', name: 'Founder'),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('approve_button_task-err')));
    await tester.pumpAndSettle();

    // Error toast appears and Approve button is restored after rollback.
    expect(find.textContaining('Failed to approve'), findsOneWidget);
    expect(find.byKey(const Key('approve_button_task-err')), findsOneWidget);
  });
}
