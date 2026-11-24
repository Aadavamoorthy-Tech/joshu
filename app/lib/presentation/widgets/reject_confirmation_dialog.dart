import 'package:flutter/material.dart';

/// Result returned when the user closes [RejectConfirmationDialog].
class RejectDialogResult {
  final bool confirmed;
  final String? reason;

  const RejectDialogResult({
    required this.confirmed,
    this.reason,
  });
}

/// Confirmation dialog capturing an optional rejection reason before rejecting a task.
class RejectConfirmationDialog extends StatefulWidget {
  final String taskTitle;

  const RejectConfirmationDialog({
    super.key,
    required this.taskTitle,
  });

  static Future<RejectDialogResult?> show(
    BuildContext context, {
    required String taskTitle,
  }) {
    return showDialog<RejectDialogResult>(
      context: context,
      builder: (_) => RejectConfirmationDialog(taskTitle: taskTitle),
    );
  }

  @override
  State<RejectConfirmationDialog> createState() =>
      _RejectConfirmationDialogState();
}

class _RejectConfirmationDialogState extends State<RejectConfirmationDialog> {
  static const _quickReasons = <String>[
    'Already scheduled',
    'Not relevant',
    'Declined elsewhere',
  ];

  final TextEditingController _reasonController = TextEditingController();

  @override
  void dispose() {
    _reasonController.dispose();
    super.dispose();
  }

  void _applyQuickReason(String suggestion) {
    _reasonController.text = suggestion;
    _reasonController.selection = TextSelection.fromPosition(
      TextPosition(offset: suggestion.length),
    );
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final colorScheme = theme.colorScheme;

    return AlertDialog(
      title: const Text('Reject Task?'),
      content: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 420),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Are you sure you want to reject "${widget.taskTitle}"? You can still approve it later if needed.',
                style: theme.textTheme.bodyMedium?.copyWith(
                  color: colorScheme.onSurfaceVariant,
                ),
              ),
              const SizedBox(height: 16),
              Text(
                'Optional: Why are you rejecting?',
                style: theme.textTheme.labelLarge,
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: _quickReasons
                    .map(
                      (reason) => ActionChip(
                        label: Text(reason),
                        onPressed: () => _applyQuickReason(reason),
                      ),
                    )
                    .toList(),
              ),
              const SizedBox(height: 12),
              TextField(
                key: const Key('reject_reason_field'),
                controller: _reasonController,
                maxLines: 3,
                maxLength: 500,
                decoration: const InputDecoration(
                  hintText: 'Add a note (optional)...',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          key: const Key('reject_dialog_cancel'),
          onPressed: () => Navigator.of(context).pop(
            const RejectDialogResult(confirmed: false),
          ),
          child: const Text('Cancel'),
        ),
        FilledButton(
          key: const Key('reject_dialog_confirm'),
          style: FilledButton.styleFrom(
            backgroundColor: colorScheme.error,
            foregroundColor: colorScheme.onError,
          ),
          onPressed: () {
            final text = _reasonController.text.trim();
            Navigator.of(context).pop(
              RejectDialogResult(
                confirmed: true,
                reason: text.isEmpty ? null : text,
              ),
            );
          },
          child: const Text('Reject'),
        ),
      ],
    );
  }
}
