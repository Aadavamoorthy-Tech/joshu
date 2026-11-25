/// Approval lifecycle status of an extracted meeting or administrative task.
enum TaskStatus {
  pending,
  approved,
  rejected;

  static TaskStatus fromApi(String? raw) {
    return switch ((raw ?? '').trim().toLowerCase()) {
      'approved' => TaskStatus.approved,
      'rejected' => TaskStatus.rejected,
      _ => TaskStatus.pending,
    };
  }

  String get apiValue => name;

  String get label => switch (this) {
        TaskStatus.pending => 'Pending',
        TaskStatus.approved => 'Approved',
        TaskStatus.rejected => 'Rejected',
      };
}

/// Filter chips displayed on the approval dashboard.
enum TaskFilter {
  all,
  pending,
  approved,
  rejected;

  String get apiValue => name;

  String get label => switch (this) {
        TaskFilter.all => 'All',
        TaskFilter.pending => 'Pending',
        TaskFilter.approved => 'Approved',
        TaskFilter.rejected => 'Rejected',
      };
}

/// Per-status task counts returned by `GET /tasks` or derived locally.
class TaskCounts {
  final int all;
  final int pending;
  final int approved;
  final int rejected;

  const TaskCounts({
    required this.all,
    required this.pending,
    required this.approved,
    required this.rejected,
  });

  factory TaskCounts.fromJson(Map<String, dynamic> json) => TaskCounts(
        all: (json['all'] as num?)?.toInt() ?? 0,
        pending: (json['pending'] as num?)?.toInt() ?? 0,
        approved: (json['approved'] as num?)?.toInt() ?? 0,
        rejected: (json['rejected'] as num?)?.toInt() ?? 0,
      );

  factory TaskCounts.fromTasks(List<TaskModel> tasks) {
    var pending = 0;
    var approved = 0;
    var rejected = 0;
    for (final task in tasks) {
      switch (task.status) {
        case TaskStatus.pending:
          pending++;
        case TaskStatus.approved:
          approved++;
        case TaskStatus.rejected:
          rejected++;
      }
    }
    return TaskCounts(
      all: tasks.length,
      pending: pending,
      approved: approved,
      rejected: rejected,
    );
  }

  int countFor(TaskFilter filter) => switch (filter) {
        TaskFilter.all => all,
        TaskFilter.pending => pending,
        TaskFilter.approved => approved,
        TaskFilter.rejected => rejected,
      };
}

/// Immutable representation of a meeting invitation / task awaiting user review.
class TaskModel {
  final String id;
  final int userId;
  final String title;
  final String description;
  final DateTime? scheduledFor;
  final String source;
  final TaskStatus status;
  final String? organizer;
  final List<String> attendees;
  final String? calendarEventLink;
  final Map<String, dynamic> rawData;
  final DateTime? createdAt;
  final DateTime? updatedAt;
  final DateTime? approvedAt;
  final DateTime? rejectedAt;
  final String? rejectionReason;
  final bool approvedByUser;

  const TaskModel({
    required this.id,
    required this.userId,
    required this.title,
    required this.description,
    this.scheduledFor,
    required this.source,
    required this.status,
    this.organizer,
    this.attendees = const [],
    this.calendarEventLink,
    this.rawData = const {},
    this.createdAt,
    this.updatedAt,
    this.approvedAt,
    this.rejectedAt,
    this.rejectionReason,
    this.approvedByUser = false,
  });

  static DateTime? _parseDate(Object? value) {
    if (value is! String || value.isEmpty) return null;
    return DateTime.tryParse(value)?.toLocal();
  }

  /// End time parsed from `raw_data.end_time` when available.
  DateTime? get endTime => _parseDate(rawData['end_time']);

  factory TaskModel.fromJson(Map<String, dynamic> json) {
    final raw = json['raw_data'] is Map<String, dynamic>
        ? Map<String, dynamic>.from(json['raw_data'] as Map<String, dynamic>)
        : <String, dynamic>{};

    final rawAttendees = json['attendees'] ?? raw['attendees'];
    final attendees = rawAttendees is List
        ? rawAttendees.map((e) => e.toString()).where((e) => e.isNotEmpty).toList()
        : <String>[];

    return TaskModel(
      id: (json['id'] ?? '').toString(),
      userId: (json['user_id'] as num?)?.toInt() ?? 0,
      title: (json['title'] as String?)?.trim().isNotEmpty == true
          ? (json['title'] as String).trim()
          : 'Untitled Meeting',
      description: (json['description'] as String?) ?? '',
      scheduledFor: _parseDate(json['scheduled_for']),
      source: (json['source'] as String?) ?? 'email',
      status: TaskStatus.fromApi(json['status'] as String?),
      organizer: (json['organizer'] as String?) ?? (raw['organizer'] as String?),
      attendees: attendees,
      calendarEventLink: (json['calendar_event_link'] as String?) ??
          (raw['calendar_event_link'] as String?),
      rawData: raw,
      createdAt: _parseDate(json['created_at']),
      updatedAt: _parseDate(json['updated_at']),
      approvedAt: _parseDate(json['approved_at']),
      rejectedAt: _parseDate(json['rejected_at']),
      rejectionReason: json['rejection_reason'] as String?,
      approvedByUser: (json['approved_by_user'] as bool?) ?? false,
    );
  }

  TaskModel copyWith({
    TaskStatus? status,
    DateTime? approvedAt,
    DateTime? rejectedAt,
    String? rejectionReason,
    bool clearRejectionReason = false,
    bool? approvedByUser,
    DateTime? updatedAt,
  }) =>
      TaskModel(
        id: id,
        userId: userId,
        title: title,
        description: description,
        scheduledFor: scheduledFor,
        source: source,
        status: status ?? this.status,
        organizer: organizer,
        attendees: attendees,
        calendarEventLink: calendarEventLink,
        rawData: rawData,
        createdAt: createdAt,
        updatedAt: updatedAt ?? this.updatedAt,
        approvedAt: approvedAt ?? this.approvedAt,
        rejectedAt: rejectedAt ?? this.rejectedAt,
        rejectionReason: clearRejectionReason
            ? null
            : (rejectionReason ?? this.rejectionReason),
        approvedByUser: approvedByUser ?? this.approvedByUser,
      );
}

/// Paginated response payload from `GET /tasks`.
class TaskListResponse {
  final List<TaskModel> tasks;
  final int total;
  final TaskCounts counts;

  const TaskListResponse({
    required this.tasks,
    required this.total,
    required this.counts,
  });

  factory TaskListResponse.fromJson(Map<String, dynamic> json) {
    final rawList = json['tasks'] as List<dynamic>? ?? const [];
    final tasks = rawList
        .whereType<Map<String, dynamic>>()
        .map(TaskModel.fromJson)
        .toList();

    final counts = json['counts'] is Map<String, dynamic>
        ? TaskCounts.fromJson(json['counts'] as Map<String, dynamic>)
        : TaskCounts.fromTasks(tasks);

    return TaskListResponse(
      tasks: tasks,
      total: (json['total'] as num?)?.toInt() ?? tasks.length,
      counts: counts,
    );
  }
}

/// Summary payload from `POST /tasks/sync`.
class GmailSyncSummary {
  final int fetchedMessages;
  final int createdTasks;
  final int skippedDuplicates;

  const GmailSyncSummary({
    required this.fetchedMessages,
    required this.createdTasks,
    required this.skippedDuplicates,
  });

  factory GmailSyncSummary.fromJson(Map<String, dynamic> json) =>
      GmailSyncSummary(
        fetchedMessages: (json['fetched_messages'] as num?)?.toInt() ?? 0,
        createdTasks: (json['created_tasks'] as num?)?.toInt() ?? 0,
        skippedDuplicates: (json['skipped_duplicates'] as num?)?.toInt() ?? 0,
      );
}
