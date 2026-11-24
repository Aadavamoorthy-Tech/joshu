import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/models/user_profile.dart';
import 'presentation/screens/sign_in_screen.dart';
import 'presentation/screens/tasks_list_screen.dart';
import 'providers/auth_provider.dart';

void main() {
  runApp(const ProviderScope(child: ChiefOfStaffApp()));
}

class ChiefOfStaffApp extends StatelessWidget {
  const ChiefOfStaffApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Joshu — Personal AI Chief of Staff',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF1E3A8A),
          brightness: Brightness.light,
        ),
        useMaterial3: true,
      ),
      initialRoute: '/',
      routes: {
        '/': (_) => const HomePage(),
        '/signin': (_) => const SignInScreen(),
        '/home': (_) => const HomePage(),
      },
    );
  }
}

/// Root authentication gate routing between SignInScreen and InboxScreen.
class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);

    return authState.when(
      loading: () => const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              CircularProgressIndicator(),
              SizedBox(height: 16),
              Text('Restoring session...'),
            ],
          ),
        ),
      ),
      error: (error, stack) => const SignInScreen(),
      data: (auth) {
        if (auth.status != AuthStatus.signedIn || auth.user == null) {
          return const SignInScreen();
        }

        return InboxScreen(
          user: auth.user!,
          googleReconnectRequired: auth.googleReconnectRequired,
        );
      },
    );
  }
}

/// Authenticated home screen delegating to the Phase 3 TasksListScreen approval workflow.
class InboxScreen extends StatelessWidget {
  final UserProfile user;
  final bool googleReconnectRequired;

  const InboxScreen({
    super.key,
    required this.user,
    this.googleReconnectRequired = false,
  });

  @override
  Widget build(BuildContext context) {
    return TasksListScreen(
      user: user,
      googleReconnectRequired: googleReconnectRequired,
    );
  }
}
