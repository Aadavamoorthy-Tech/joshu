import 'package:flutter/material.dart';
import '../../core/models/task_model.dart';
import '../utils/task_formatters.dart';

/// Executive task review card displaying meeting details and approve/reject actions.
class TaskCard extends StatelessWidget {
  final TaskModel task;
  final bool isBusy;
  final VoidCallback onApprove;
  final VoidCallback onReject;
  final VoidCallback onDetails;
  final ValueChanged<String>? onOpenLink;

  const TaskCard({
    super.key,
    required this.task,
    required this.isBusy,
    required this.onApprove,
    required this.onReject,
    required this.onDetails,
    this.onOpenLink,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    final statusVisual = _StatusVisual.fromStatus(task.status, colorScheme);
    final attendeeCount = task.attendees.length;
    final attendeeLabel = attendeeCount == 1
        ? '1 attendee'
        : '$attendeeCount attendees';

    return Card(
      key: Key('task_card_${task.id}'),
      elevation: 0,
      margin: const EdgeInsets.only(bottom: 12),
      color: statusVisual.cardTint,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: BorderSide(color: statusVisual.borderColor),
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 38,
                  height: 38,
                  decoration: BoxDecoration(
                    color: statusVisual.badgeBg,
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(
                    task.source == 'calendar'
                        ? Icons.event_outlined
                        : Icons.mail_outline_rounded,
                    size: 20,
                    color: statusVisual.badgeFg,
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        task.title,
                        style: theme.textTheme.titleMedium?.copyWith(
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        formatTaskDateTimeShort(task.scheduledFor),
                        style: theme.textTheme.bodySmall?.copyWith(
                          color: colorScheme.onSurfaceVariant,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 10),
                _StatusBadge(status: task.status, visual: statusVisual),
              ],
            ),
            const SizedBox(height: 14),
            Wrap(
              spacing: 16,
              runSpacing: 8,
              children: [
                if (task.organizer != null && task.organizer!.isNotEmpty)
                  _MetaRow(
                    icon: Icons.person_outline_rounded,
                    text: task.organizer!,
                  ),
                if (attendeeCount > 0)
                  _MetaRow(
                    icon: Icons.group_outlined,
                    text: attendeeLabel,
                  ),
                if (task.calendarEventLink != null &&
                    task.calendarEventLink!.isNotEmpty)
                  InkWell(
                    key: Key('task_link_${task.id}'),
                    borderRadius: BorderRadius.circular(6),
                    onTap: () => onOpenLink?.call(task.calendarEventLink!),
                    child: Padding(
                      padding: const EdgeInsets.symmetric(vertical: 2),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            Icons.videocam_outlined,
                            size: 16,
                            color: colorScheme.primary,
                          ),
                          const SizedBox(width: 6),
                          Text(
                            formatShortLinkLabel(task.calendarEventLink!),
                            style: theme.textTheme.bodySmall?.copyWith(
                              color: colorScheme.primary,
                              decoration: TextDecoration.underline,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
            if (task.status == TaskStatus.rejected &&
                task.rejectionReason != null &&
                task.rejectionReason!.isNotEmpty) ...[
              const SizedBox(height: 12),
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                decoration: BoxDecoration(
                  color: colorScheme.errorContainer.withValues(alpha: 0.45),
                  borderRadius: BorderRadius.circular(8),
                ),
                child: Text(
                  'Rejection reason: ${task.rejectionReason}',
                  style: theme.textTheme.bodySmall?.copyWith(
                    color: colorScheme.onErrorContainer,
                  ),
                ),
              ),
            ],
            const SizedBox(height: 16),
            const Divider(height: 1),
            const SizedBox(height: 12),
            Wrap(
              spacing: 10,
              runSpacing: 8,
              crossAxisAlignment: WrapCrossAlignment.center,
              children: [
                if (task.status == TaskStatus.pending) ...[
                  FilledButton.icon(
                    key: Key('approve_button_${task.id}'),
                    onPressed: isBusy ? null : onApprove,
                    style: FilledButton.styleFrom(
                      backgroundColor: const Color(0xFF15803D),
                      foregroundColor: Colors.white,
                    ),
                    icon: isBusy
                        ? const SizedBox(
                            width: 14,
                            height: 14,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          )
                        : const Icon(Icons.check_rounded, size: 18),
                    label: const Text('Approve'),
                  ),
                  OutlinedButton.icon(
                    key: Key('reject_button_${task.id}'),
                    onPressed: isBusy ? null : onReject,
                    style: OutlinedButton.styleFrom(
                      foregroundColor: colorScheme.error,
                      side: BorderSide(color: colorScheme.error),
                    ),
                    icon: const Icon(Icons.close_rounded, size: 18),
                    label: const Text('Reject'),
                  ),
                ] else ...[
                  Text(
                    task.status == TaskStatus.approved
                        ? 'Approved ${task.approvedAt != null ? "• ${formatTaskDateTimeShort(task.approvedAt)}" : ""}'
                        : 'Rejected ${task.rejectedAt != null ? "• ${formatTaskDateTimeShort(task.rejectedAt)}" : ""}',
                    style: theme.textTheme.bodySmall?.copyWith(
                      color: statusVisual.badgeFg,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ],
                TextButton.icon(
                  key: Key('details_button_${task.id}'),
                  onPressed: onDetails,
                  icon: const Icon(Icons.info_outline_rounded, size: 18),
                  label: const Text('Details'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}

class _MetaRow extends StatelessWidget {
  final IconData icon;
  final String text;

  const _MetaRow({
    required this.icon,
    required this.text,
  });

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 16, color: colorScheme.onSurfaceVariant),
        const SizedBox(width: 6),
        Flexible(
          child: Text(
            text,
            overflow: TextOverflow.ellipsis,
            style: theme.textTheme.bodySmall?.copyWith(
              color: colorScheme.onSurfaceVariant,
            ),
          ),
        ),
      ],
    );
  }
}

class _StatusBadge extends StatelessWidget {
  final TaskStatus status;
  final _StatusVisual visual;

  const _StatusBadge({
    required this.status,
    required this.visual,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: visual.badgeBg,
        borderRadius: BorderRadius.circular(8),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(visual.icon, size: 14, color: visual.badgeFg),
          const SizedBox(width: 5),
          Text(
            status.label,
            style: Theme.of(context).textTheme.labelSmall?.copyWith(
                  color: visual.badgeFg,
                  fontWeight: FontWeight.w700,
                ),
          ),
        ],
      ),
    );
  }
}

class _StatusVisual {
  final Color cardTint;
  final Color borderColor;
  final Color badgeBg;
  final Color badgeFg;
  final IconData icon;

  const _StatusVisual({
    required this.cardTint,
    required this.borderColor,
    required this.badgeBg,
    required this.badgeFg,
    required this.icon,
  });

  factory _StatusVisual.fromStatus(TaskStatus status, ColorScheme scheme) {
    return switch (status) {
      TaskStatus.approved => const _StatusVisual(
          cardTint: Color(0xFFF0FDF4),
          borderColor: Color(0xFFBBF7D0),
          badgeBg: Color(0xFFDCFCE7),
          badgeFg: Color(0xFF166534),
          icon: Icons.check_circle_outline_rounded,
        ),
      TaskStatus.rejected => _StatusVisual(
          cardTint: scheme.errorContainer.withValues(alpha: 0.22),
          borderColor: scheme.error.withValues(alpha: 0.35),
          badgeBg: scheme.errorContainer,
          badgeFg: scheme.onErrorContainer,
          icon: Icons.cancel_outlined,
        ),
      TaskStatus.pending => _StatusVisual(
          cardTint: scheme.surface,
          borderColor: scheme.outlineVariant,
          badgeBg: const Color(0xFFFEF3C7),
          badgeFg: const Color(0xFF92400E),
          icon: Icons.schedule_rounded,
        ),
    };
  }
}
