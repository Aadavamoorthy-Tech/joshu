import 'package:flutter_riverpod/flutter_riverpod.dart';
import '../core/models/task_model.dart';
import '../core/services/task_service.dart';
import 'core_providers.dart';

/// Singleton TaskService wired to the authenticated ApiClient.
final taskServiceProvider = Provider<TaskService>((ref) {
  final apiClient = ref.watch(apiClientProvider);
  return TaskService(apiClient: apiClient);
});

/// Immutable state for the task approval dashboard.
class TasksState {
  final List<TaskModel> allTasks;
  final TaskFilter activeFilter;
  final Set<String> inFlightTaskIds;
  final bool isSyncing;

  const TasksState({
    required this.allTasks,
    this.activeFilter = TaskFilter.all,
    this.inFlightTaskIds = const {},
    this.isSyncing = false,
  });

  /// Per-status counts kept strictly in sync with [allTasks] across optimistic updates.
  TaskCounts get counts => TaskCounts.fromTasks(allTasks);

  /// Tasks matching the currently selected [activeFilter].
  List<TaskModel> get filteredTasks {
    return switch (activeFilter) {
      TaskFilter.all => allTasks,
      TaskFilter.pending =>
        allTasks.where((t) => t.status == TaskStatus.pending).toList(),
      TaskFilter.approved =>
        allTasks.where((t) => t.status == TaskStatus.approved).toList(),
      TaskFilter.rejected =>
        allTasks.where((t) => t.status == TaskStatus.rejected).toList(),
    };
  }

  bool isTaskBusy(String taskId) => inFlightTaskIds.contains(taskId);

  TasksState copyWith({
    List<TaskModel>? allTasks,
    TaskFilter? activeFilter,
    Set<String>? inFlightTaskIds,
    bool? isSyncing,
  }) =>
      TasksState(
        allTasks: allTasks ?? this.allTasks,
        activeFilter: activeFilter ?? this.activeFilter,
        inFlightTaskIds: inFlightTaskIds ?? this.inFlightTaskIds,
        isSyncing: isSyncing ?? this.isSyncing,
      );
}

/// Manages fetching tasks, filtering, Gmail sync, and optimistic approve/reject mutations.
class TasksController extends AsyncNotifier<TasksState> {
  @override
  Future<TasksState> build() async {
    final service = ref.read(taskServiceProvider);
    final response = await service.fetchTasks(filter: TaskFilter.all);
    return TasksState(allTasks: response.tasks);
  }

  /// Reloads tasks from the backend while preserving the active filter.
  Future<void> refresh() async {
    final currentFilter = state.valueOrNull?.activeFilter ?? TaskFilter.all;
    final service = ref.read(taskServiceProvider);
    try {
      final response = await service.fetchTasks(filter: TaskFilter.all);
      state = AsyncValue.data(
        TasksState(
          allTasks: response.tasks,
          activeFilter: currentFilter,
        ),
      );
    } catch (e, st) {
      if (state.valueOrNull == null) {
        state = AsyncValue.error(e, st);
      }
      rethrow;
    }
  }

  /// Switches the active status filter chip immediately.
  void setFilter(TaskFilter filter) {
    final current = state.valueOrNull;
    if (current == null) return;
    state = AsyncValue.data(current.copyWith(activeFilter: filter));
  }

  /// Optimistically approves a task, confirms with backend, and rolls back on failure.
  Future<void> approveTask(String taskId) async {
    final current = state.valueOrNull;
    if (current == null || current.isTaskBusy(taskId)) return;

    final previousTasks = current.allTasks;
    final now = DateTime.now().toLocal();
    final optimistic = previousTasks.map((task) {
      if (task.id != taskId) return task;
      return task.copyWith(
        status: TaskStatus.approved,
        approvedAt: task.approvedAt ?? now,
        approvedByUser: true,
        updatedAt: now,
      );
    }).toList();

    state = AsyncValue.data(
      current.copyWith(
        allTasks: optimistic,
        inFlightTaskIds: {...current.inFlightTaskIds, taskId},
      ),
    );

    try {
      final confirmed = await ref.read(taskServiceProvider).approveTask(taskId);
      final latest = state.valueOrNull;
      if (latest == null) return;

      final reconciled = confirmed != null
          ? latest.allTasks
              .map((task) => task.id == taskId ? confirmed : task)
              .toList()
          : latest.allTasks;

      state = AsyncValue.data(
        latest.copyWith(
          allTasks: reconciled,
          inFlightTaskIds: {...latest.inFlightTaskIds}..remove(taskId),
        ),
      );
    } catch (_) {
      final latest = state.valueOrNull;
      if (latest != null) {
        state = AsyncValue.data(
          latest.copyWith(
            allTasks: previousTasks,
            inFlightTaskIds: {...latest.inFlightTaskIds}..remove(taskId),
          ),
        );
      }
      rethrow;
    }
  }

  /// Optimistically rejects a task with an optional reason, confirms with backend, and rolls back on failure.
  Future<void> rejectTask(String taskId, {String? reason}) async {
    final current = state.valueOrNull;
    if (current == null || current.isTaskBusy(taskId)) return;

    final previousTasks = current.allTasks;
    final trimmedReason =
        (reason != null && reason.trim().isNotEmpty) ? reason.trim() : null;
    final now = DateTime.now().toLocal();

    final optimistic = previousTasks.map((task) {
      if (task.id != taskId) return task;
      return task.copyWith(
        status: TaskStatus.rejected,
        rejectedAt: task.rejectedAt ?? now,
        rejectionReason: trimmedReason ?? task.rejectionReason,
        approvedByUser: false,
        updatedAt: now,
      );
    }).toList();

    state = AsyncValue.data(
      current.copyWith(
        allTasks: optimistic,
        inFlightTaskIds: {...current.inFlightTaskIds, taskId},
      ),
    );

    try {
      final confirmed = await ref
          .read(taskServiceProvider)
          .rejectTask(taskId, reason: trimmedReason);
      final latest = state.valueOrNull;
      if (latest == null) return;

      final reconciled = confirmed != null
          ? latest.allTasks
              .map((task) => task.id == taskId ? confirmed : task)
              .toList()
          : latest.allTasks;

      state = AsyncValue.data(
        latest.copyWith(
          allTasks: reconciled,
          inFlightTaskIds: {...latest.inFlightTaskIds}..remove(taskId),
        ),
      );
    } catch (_) {
      final latest = state.valueOrNull;
      if (latest != null) {
        state = AsyncValue.data(
          latest.copyWith(
            allTasks: previousTasks,
            inFlightTaskIds: {...latest.inFlightTaskIds}..remove(taskId),
          ),
        );
      }
      rethrow;
    }
  }

  /// Triggers on-demand Gmail polling and reloads the task list.
  Future<GmailSyncSummary> syncGmail() async {
    final current = state.valueOrNull;
    if (current != null) {
      state = AsyncValue.data(current.copyWith(isSyncing: true));
    }

    try {
      final service = ref.read(taskServiceProvider);
      final summary = await service.syncGmail();
      final response = await service.fetchTasks(filter: TaskFilter.all);
      final filter = state.valueOrNull?.activeFilter ?? TaskFilter.all;
      state = AsyncValue.data(
        TasksState(
          allTasks: response.tasks,
          activeFilter: filter,
          isSyncing: false,
        ),
      );
      return summary;
    } catch (_) {
      final latest = state.valueOrNull;
      if (latest != null) {
        state = AsyncValue.data(latest.copyWith(isSyncing: false));
      }
      rethrow;
    }
  }
}

/// Riverpod AsyncNotifier provider for the approval task queue.
final tasksControllerProvider =
    AsyncNotifierProvider<TasksController, TasksState>(
  TasksController.new,
);
