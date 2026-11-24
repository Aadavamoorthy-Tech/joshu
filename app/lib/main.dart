import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/models/user_profile.dart';
import 'providers/auth_provider.dart';

void main() {
  runApp(const ProviderScope(child: ChiefOfStaffApp()));
}

class ChiefOfStaffApp extends StatelessWidget {
  const ChiefOfStaffApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Personal AI Chief of Staff',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
        useMaterial3: true,
      ),
      home: const HomePage(),
    );
  }
}

class HomePage extends ConsumerWidget {
  const HomePage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final authState = ref.watch(authControllerProvider);

    return authState.when(
      loading: () => const Scaffold(
        body: Center(child: CircularProgressIndicator()),
      ),
      error: (error, stack) => Scaffold(
        appBar: AppBar(title: const Text('Error')),
        body: Center(child: Text('Error: $error')),
      ),
      data: (auth) {
        if (auth.status == AuthStatus.signedOut) {
          return const SignInScreen();
        }

        return InboxScreen(user: auth.user);
      },
    );
  }
}

class SignInScreen extends StatelessWidget {
  const SignInScreen({super.key});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Sign In')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.center,
              children: [
                Text(
                  'Personal AI Chief of Staff',
                  style: Theme.of(context).textTheme.headlineMedium,
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 16),
                const Text(
                  'Sign in with Google to get started with meeting approvals and task management.',
                  textAlign: TextAlign.center,
                ),
                const SizedBox(height: 32),
                Consumer(
                  builder: (context, ref, child) {
                    return FilledButton.icon(
                      icon: const Icon(Icons.login),
                      label: const Text('Sign in with Google'),
                      onPressed: () {
                        // TODO: Implement OAuth sign-in flow
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(content: Text('OAuth flow not yet implemented')),
                        );
                      },
                    );
                  },
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class InboxScreen extends StatelessWidget {
  final UserProfile? user;

  const InboxScreen({super.key, this.user});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Inbox'),
        actions: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Center(
              child: Text(user?.email ?? 'User'),
            ),
          ),
        ],
      ),
      body: const Center(
        child: Text('No pending approvals'),
      ),
    );
  }
}
