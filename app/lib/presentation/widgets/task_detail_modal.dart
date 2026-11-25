import 'package:flutter/material.dart';
import '../../core/models/task_model.dart';
import '../utils/task_formatters.dart';

/// Modal dialog presenting complete meeting details, attendees, link, and approve/reject actions.
class TaskDetailModal extends StatelessWidget {
  final TaskModel task;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  final ValueChanged<String>? onOpenLink;

  const TaskDetailModal({
    super.key,
    required this.task,
    required this.onApprove,
    required this.onReject,
    this.onOpenLink,
  });

  static Future<void> show(
    BuildContext context, {
    required TaskModel task,
    required VoidCallback onApprove,
    required VoidCallback onReject,
    ValueChanged<String>? onOpenLink,
  }) {
    return showDialog<void>(
      context: context,
      builder: (_) => TaskDetailModal(
        task: task,
        onApprove: onApprove,
        onReject: onReject,
        onOpenLink: onOpenLink,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return Dialog(
      key: Key('task_detail_modal_${task.id}'),
      insetPadding: const EdgeInsets.all(20),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 560, maxHeight: 680),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(24, 20, 12, 12),
              child: Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          task.title,
                          style: theme.textTheme.titleLarge?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Status: ${task.status.label}',
                          style: theme.textTheme.labelMedium?.copyWith(
                            color: task.status == TaskStatus.approved
                                ? const Color(0xFF166534)
                                : task.status == TaskStatus.rejected
                                    ? colorScheme.error
                                    : const Color(0xFF92400E),
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                  ),
                  IconButton(
                    tooltip: 'Close',
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close_rounded),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),
            Flexible(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    _SectionLabel(title: 'When'),
                    Text(
                      formatTaskDateLong(task.scheduledFor),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      formatTaskTimeRange(task.scheduledFor, task.endTime),
                      style: theme.textTheme.bodyMedium?.copyWith(
                        color: colorScheme.onSurfaceVariant,
                      ),
                    ),
                    const SizedBox(height: 20),
                    _SectionLabel(title: 'Who'),
                    if (task.organizer != null && task.organizer!.isNotEmpty)
                      Padding(
                        padding: const EdgeInsets.only(bottom: 8),
                        child: Text(
                          'Organizer: ${task.organizer}',
                          style: theme.textTheme.bodyMedium,
                        ),
                      ),
                    if (task.attendees.isEmpty)
                      Text(
                        'No attendees listed',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                        ),
                      )
                    else ...[
                      Text(
                        'Attendees (${task.attendees.length}):',
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 6),
                      ...task.attendees.map(
                        (email) => Padding(
                          padding: const EdgeInsets.only(bottom: 4),
                          child: Row(
                            children: [
                              Icon(
                                Icons.circle,
                                size: 6,
                                color: colorScheme.outline,
                              ),
                              const SizedBox(width: 8),
                              Expanded(
                                child: Text(
                                  email,
                                  style: theme.textTheme.bodyMedium,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),
                    ],
                    if (task.calendarEventLink != null &&
                        task.calendarEventLink!.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      _SectionLabel(title: 'Meeting Link'),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        decoration: BoxDecoration(
                          color: colorScheme.surfaceContainerHighest
                              .withValues(alpha: 0.45),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Row(
                          children: [
                            Expanded(
                              child: Text(
                                task.calendarEventLink!,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: theme.textTheme.bodySmall?.copyWith(
                                  color: colorScheme.primary,
                                ),
                              ),
                            ),
                            const SizedBox(width: 8),
                            FilledButton.tonalIcon(
                              key: Key('modal_open_link_${task.id}'),
                              onPressed: () =>
                                  onOpenLink?.call(task.calendarEventLink!),
                              icon: const Icon(Icons.open_in_new_rounded, size: 16),
                              label: const Text('Open'),
                            ),
                          ],
                        ),
                      ),
                    ],
                    if (task.description.trim().isNotEmpty) ...[
                      const SizedBox(height: 20),
                      _SectionLabel(title: 'Description'),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          border: Border.all(color: colorScheme.outlineVariant),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: SelectableText(
                          task.description.trim(),
                          style: theme.textTheme.bodySmall?.copyWith(height: 1.5),
                        ),
                      ),
                    ],
                    if (task.status == TaskStatus.rejected &&
                        task.rejectionReason != null &&
                        task.rejectionReason!.isNotEmpty) ...[
                      const SizedBox(height: 20),
                      _SectionLabel(title: 'Rejection Reason'),
                      Container(
                        width: double.infinity,
                        padding: const EdgeInsets.all(14),
                        decoration: BoxDecoration(
                          color: colorScheme.errorContainer.withValues(alpha: 0.5),
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: Text(
                          task.rejectionReason!,
                          style: theme.textTheme.bodyMedium?.copyWith(
                            color: colorScheme.onErrorContainer,
                          ),
                        ),
                      ),
                    ],
                  ],
                ),
              ),
            ),
            const Divider(height: 1),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.end,
                children: [
                  if (task.status != TaskStatus.approved)
                    FilledButton.icon(
                      key: Key('modal_approve_${task.id}'),
                      style: FilledButton.styleFrom(
                        backgroundColor: const Color(0xFF15803D),
                        foregroundColor: Colors.white,
                      ),
                      onPressed: () {
                        Navigator.of(context).pop();
                        onApprove();
                      },
                      icon: const Icon(Icons.check_rounded, size: 18),
                      label: const Text('Approve'),
                    ),
                  if (task.status != TaskStatus.rejected) ...[
                    const SizedBox(width: 10),
                    OutlinedButton.icon(
                      key: Key('modal_reject_${task.id}'),
                      style: OutlinedButton.styleFrom(
                        foregroundColor: colorScheme.error,
                        side: BorderSide(color: colorScheme.error),
                      ),
                      onPressed: () {
                        Navigator.of(context).pop();
                        onReject();
                      },
                      icon: const Icon(Icons.close_rounded, size: 18),
                      label: const Text('Reject'),
                    ),
                  ],
                  const SizedBox(width: 10),
                  TextButton(
                    onPressed: () => Navigator.of(context).pop(),
                    child: const Text('Close'),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SectionLabel extends StatelessWidget {
  final String title;

  const _SectionLabel({required this.title});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 6),
      child: Text(
        title.toUpperCase(),
        style: Theme.of(context).textTheme.labelSmall?.copyWith(
              letterSpacing: 0.8,
              fontWeight: FontWeight.w700,
              color: Theme.of(context).colorScheme.primary,
            ),
      ),
    );
  }
}
