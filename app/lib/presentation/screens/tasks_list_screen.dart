import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../../core/models/task_model.dart';
import '../../core/models/user_profile.dart';
import '../../core/network/api_exception.dart';
import '../../providers/auth_provider.dart';
import '../../providers/tasks_provider.dart';
import '../utils/task_formatters.dart';
import '../widgets/reject_confirmation_dialog.dart';
import '../widgets/task_card.dart';
import '../widgets/task_detail_modal.dart';

/// Main approval dashboard displaying extracted Gmail tasks with status filtering and optimistic actions.
class TasksListScreen extends ConsumerWidget {
  final UserProfile user;
  final bool googleReconnectRequired;

  const TasksListScreen({
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

  void _showToast(BuildContext context, String message, {bool isError = false}) {
    if (!context.mounted) return;
    final messenger = ScaffoldMessenger.of(context);
    messenger.hideCurrentSnackBar();
    messenger.showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: isError ? Theme.of(context).colorScheme.error : null,
        behavior: SnackBarBehavior.floating,
      ),
    );
  }

  Future<void> _handleApprove(
    BuildContext context,
    WidgetRef ref,
    TaskModel task,
  ) async {
    try {
      await ref.read(tasksControllerProvider.notifier).approveTask(task.id);
      if (context.mounted) {
        _showToast(context, 'Task approved!');
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        _showToast(context, 'Failed to approve: ${e.message}', isError: true);
      }
    } catch (_) {
      if (context.mounted) {
        _showToast(
          context,
          'Could not approve task. Please try again.',
          isError: true,
        );
      }
    }
  }

  Future<void> _handleReject(
    BuildContext context,
    WidgetRef ref,
    TaskModel task,
  ) async {
    final dialogResult = await RejectConfirmationDialog.show(
      context,
      taskTitle: task.title,
    );
    if (dialogResult == null || !dialogResult.confirmed) return;

    try {
      await ref
          .read(tasksControllerProvider.notifier)
          .rejectTask(task.id, reason: dialogResult.reason);
      if (context.mounted) {
        _showToast(context, 'Task rejected');
      }
    } on ApiException catch (e) {
      if (context.mounted) {
        _showToast(context, 'Failed to reject: ${e.message}', isError: true);
      }
    } catch (_) {
      if (context.mounted) {
        _showToast(
          context,
          'Could not reject task. Please try again.',
          isError: true,
        );
      }
    }
  }

  Future<void> _handleSync(BuildContext context, WidgetRef ref) async {
    try {
      final summary =
          await ref.read(tasksControllerProvider.notifier).syncGmail();
      if (!context.mounted) return;
      final label = summary.createdTasks == 1
          ? '1 new task extracted from Gmail.'
          : '${summary.createdTasks} new tasks extracted from Gmail.';
      _showToast(context, label);
    } on ApiException catch (e) {
      if (context.mounted) {
        _showToast(context, e.message, isError: true);
      }
    } catch (_) {
      if (context.mounted) {
        _showToast(
          context,
          'Gmail sync failed. Please try again.',
          isError: true,
        );
      }
    }
  }

  Future<void> _handleOpenLink(BuildContext context, String url) async {
    final opened = await launchSafeMeetingUrl(url);
    if (!opened && context.mounted) {
      _showToast(context, 'Unable to open meeting link.', isError: true);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    final tasksAsync = ref.watch(tasksControllerProvider);
    final isSyncing = tasksAsync.valueOrNull?.isSyncing ?? false;

    return Scaffold(
      backgroundColor: colorScheme.surfaceContainerLowest,
      appBar: AppBar(
        title: const Text('My Tasks'),
        actions: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 4),
            child: FilledButton.tonalIcon(
              key: const Key('sync_gmail_button'),
              onPressed: isSyncing ? null : () => _handleSync(context, ref),
              icon: isSyncing
                  ? const SizedBox(
                      width: 14,
                      height: 14,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.sync_rounded, size: 18),
              label: Text(isSyncing ? 'Syncing...' : 'Sync Gmail'),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                CircleAvatar(
                  radius: 15,
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
                const SizedBox(width: 8),
                ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 180),
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
                constraints: const BoxConstraints(maxWidth: 840),
                child: tasksAsync.when(
                  loading: () => const Center(
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        CircularProgressIndicator(),
                        SizedBox(height: 16),
                        Text('Loading your tasks...'),
                      ],
                    ),
                  ),
                  error: (error, _) => Center(
                    child: Padding(
                      padding: const EdgeInsets.all(24),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.cloud_off_rounded,
                            size: 48,
                            color: colorScheme.error,
                          ),
                          const SizedBox(height: 12),
                          Text(
                            'Unable to load tasks',
                            style: theme.textTheme.titleMedium,
                          ),
                          const SizedBox(height: 6),
                          Text(
                            error is ApiException
                                ? error.message
                                : 'Please check your connection and try again.',
                            textAlign: TextAlign.center,
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.onSurfaceVariant,
                            ),
                          ),
                          const SizedBox(height: 16),
                          FilledButton.icon(
                            onPressed: () => ref
                                .read(tasksControllerProvider.notifier)
                                .refresh(),
                            icon: const Icon(Icons.refresh_rounded),
                            label: const Text('Retry'),
                          ),
                        ],
                      ),
                    ),
                  ),
                  data: (tasksState) {
                    final filtered = tasksState.filteredTasks;
                    final counts = tasksState.counts;

                    return Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Padding(
                          padding: const EdgeInsets.fromLTRB(20, 18, 20, 8),
                          child: Row(
                            children: [
                              Expanded(
                                child: SingleChildScrollView(
                                  scrollDirection: Axis.horizontal,
                                  child: Row(
                                    children: TaskFilter.values.map((filter) {
                                      final selected =
                                          tasksState.activeFilter == filter;
                                      final count = counts.countFor(filter);
                                      return Padding(
                                        padding:
                                            const EdgeInsets.only(right: 8),
                                        child: ChoiceChip(
                                          key: Key('filter_${filter.name}'),
                                          selected: selected,
                                          label: Text(
                                            '${filter.label} ($count)',
                                          ),
                                          onSelected: (_) => ref
                                              .read(tasksControllerProvider
                                                  .notifier)
                                              .setFilter(filter),
                                        ),
                                      );
                                    }).toList(),
                                  ),
                                ),
                              ),
                            ],
                          ),
                        ),
                        Expanded(
                          child: filtered.isEmpty
                              ? _EmptyTasksState(
                                  activeFilter: tasksState.activeFilter,
                                  hasAnyTasks: tasksState.allTasks.isNotEmpty,
                                  userName: user.name,
                                  onSync: () => _handleSync(context, ref),
                                )
                              : RefreshIndicator(
                                  onRefresh: () => ref
                                      .read(tasksControllerProvider.notifier)
                                      .refresh(),
                                  child: ListView.builder(
                                    padding: const EdgeInsets.fromLTRB(
                                      20,
                                      8,
                                      20,
                                      28,
                                    ),
                                    itemCount: filtered.length,
                                    itemBuilder: (context, index) {
                                      final task = filtered[index];
                                      return TaskCard(
                                        task: task,
                                        isBusy: tasksState.isTaskBusy(task.id),
                                        onApprove: () => _handleApprove(
                                          context,
                                          ref,
                                          task,
                                        ),
                                        onReject: () => _handleReject(
                                          context,
                                          ref,
                                          task,
                                        ),
                                        onOpenLink: (url) =>
                                            _handleOpenLink(context, url),
                                        onDetails: () => TaskDetailModal.show(
                                          context,
                                          task: task,
                                          onApprove: () => _handleApprove(
                                            context,
                                            ref,
                                            task,
                                          ),
                                          onReject: () => _handleReject(
                                            context,
                                            ref,
                                            task,
                                          ),
                                          onOpenLink: (url) =>
                                              _handleOpenLink(context, url),
                                        ),
                                      );
                                    },
                                  ),
                                ),
                        ),
                      ],
                    );
                  },
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _EmptyTasksState extends StatelessWidget {
  final TaskFilter activeFilter;
  final bool hasAnyTasks;
  final String userName;
  final VoidCallback onSync;

  const _EmptyTasksState({
    required this.activeFilter,
    required this.hasAnyTasks,
    required this.userName,
    required this.onSync,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    final bool allReviewed =
        hasAnyTasks && activeFilter == TaskFilter.pending;
    final String heading = allReviewed
        ? 'All tasks reviewed!'
        : !hasAnyTasks
            ? 'Welcome back, $userName'
            : 'No ${activeFilter.label.toLowerCase()} tasks';
    final String subtitle = allReviewed
        ? 'You have reviewed every pending meeting invitation in your queue.'
        : !hasAnyTasks
            ? 'No tasks yet. Keep checking your email or sync Gmail to import upcoming calendar invitations.'
            : 'Tasks you mark as ${activeFilter.label.toLowerCase()} will appear here.';

    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 440),
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                allReviewed
                    ? Icons.task_alt_rounded
                    : Icons.inbox_outlined,
                size: 52,
                color: allReviewed
                    ? const Color(0xFF15803D)
                    : colorScheme.outline,
              ),
              const SizedBox(height: 16),
              Text(
                heading,
                style: theme.textTheme.titleLarge,
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 8),
              Text(
                subtitle,
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
                textAlign: TextAlign.center,
              ),
              if (!hasAnyTasks) ...[
                const SizedBox(height: 20),
                FilledButton.icon(
                  onPressed: onSync,
                  icon: const Icon(Icons.sync_rounded),
                  label: const Text('Sync Gmail Now'),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
