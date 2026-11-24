import 'package:chief_of_staff/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('App initializes with Riverpod', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: ChiefOfStaffApp()),
    );
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // The app should initialize without crashing
    expect(find.byType(ChiefOfStaffApp), findsOneWidget);
  });

  testWidgets('Shows sign-in screen when signed out', (tester) async {
    await tester.pumpWidget(
      const ProviderScope(child: ChiefOfStaffApp()),
    );
    await tester.pumpAndSettle(const Duration(seconds: 2));

    // Look for sign-in button
    expect(
      find.byWidgetPredicate(
        (widget) =>
            widget is FilledButton &&
            widget.child != null &&
            widget.child.toString().contains('Google'),
      ),
      findsWidgets,
    );
  });
}
