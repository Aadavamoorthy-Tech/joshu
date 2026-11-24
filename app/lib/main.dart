import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'core/models/user_profile.dart';
import 'presentation/screens/sign_in_screen.dart';
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

class InboxScreen extends ConsumerWidget {
  final UserProfile user;
  final bool googleReconnectRequired;

  const InboxScreen({
    super.key,
    required this.user,
    this.googleReconnectRequired = false,
  });

  String _initials(String nameOrEmail) {
    final trimmed = nameOrEmail.trim();
    if (trimmed.isEmpty) return 'U';
    final parts = trimmed.split(RegExp(r'\s+'));
    if (parts.length >= 2) {
      return '${parts[0][0]}${parts[1][0]}'.toUpperCase();
    }
    return trimmed[0].toUpperCase();
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Joshu Inbox'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircleAvatar(
                  radius: 16,
                  backgroundColor: colorScheme.primaryContainer,
                  backgroundImage:
                      (user.pictureUrl != null && user.pictureUrl!.isNotEmpty)
                          ? NetworkImage(user.pictureUrl!)
                          : null,
                  child: (user.pictureUrl == null || user.pictureUrl!.isEmpty)
                      ? Text(
                          _initials(user.name.isNotEmpty ? user.name : user.email),
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: colorScheme.onPrimaryContainer,
                            fontWeight: FontWeight.w600,
                          ),
                        )
                      : null,
                ),
                const SizedBox(width: 10),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 200),
                  child: Text(
                    user.email,
                    overflow: TextOverflow.ellipsis,
                    style: theme.textTheme.bodySmall,
                  ),
                ),
              ],
            ),
          ),
          TextButton.icon(
            key: const Key('sign_out_button'),
            onPressed: () async {
              await ref.read(authControllerProvider.notifier).logout();
            },
            icon: const Icon(Icons.logout_rounded, size: 18),
            label: const Text('Sign out'),
          ),
          const SizedBox(width: 8),
        ],
      ),
      body: Column(
        children: [
          if (googleReconnectRequired)
            MaterialBanner(
              content: const Text(
                'Your Google Workspace connection needs to be refreshed to continue syncing Gmail and Calendar.',
              ),
              leading: Icon(Icons.sync_problem, color: colorScheme.error),
              actions: [
                TextButton(
                  onPressed: () async {
                    await ref.read(authControllerProvider.notifier).logout();
                  },
                  child: const Text('Reconnect'),
                ),
              ],
            ),
          Expanded(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 480),
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Icon(
                        Icons.inbox_outlined,
                        size: 52,
                        color: colorScheme.outline,
                      ),
                      const SizedBox(height: 16),
                      Text(
                        'Welcome back, ${user.name}',
                        style: theme.textTheme.titleLarge,
                        textAlign: TextAlign.center,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'No pending approvals right now. New meeting invites and administrative requests will appear here for your review.',
                        style: theme.textTheme.bodyMedium?.copyWith(
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
        ],
      ),
    );
  }
}
