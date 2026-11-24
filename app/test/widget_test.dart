import 'package:chief_of_staff/main.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('shows when the backend is reachable', (tester) async {
    final client = MockClient((request) async {
      expect(request.url.path, '/health');
      return http.Response('{"status":"ok"}', 200);
    });

    await tester.pumpWidget(ChiefOfStaffApp(client: client));
    await tester.pumpAndSettle();

    expect(find.text('Server connected'), findsOneWidget);
    expect(find.textContaining('not available yet'), findsOneWidget);
    client.close();
  });

  testWidgets('shows failure and retries', (tester) async {
    var attempts = 0;
    final client = MockClient((request) async {
      attempts++;
      return attempts == 1
          ? http.Response('unavailable', 503)
          : http.Response('{"status":"ok"}', 200);
    });

    await tester.pumpWidget(ChiefOfStaffApp(client: client));
    await tester.pumpAndSettle();
    expect(find.textContaining('Server returned HTTP 503'), findsOneWidget);

    await tester.tap(find.text('Retry'));
    await tester.pumpAndSettle();
    expect(find.text('Server connected'), findsOneWidget);
    expect(attempts, 2);
    client.close();
  });
}
