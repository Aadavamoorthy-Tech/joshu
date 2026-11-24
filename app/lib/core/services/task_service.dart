import '../models/task_model.dart';
import '../network/api_client.dart';

/// API service for loading, syncing, approving, and rejecting extracted tasks.
class TaskService {
  final ApiClient _apiClient;

  TaskService({required ApiClient apiClient}) : _apiClient = apiClient;

  /// Fetches tasks for the authenticated user, optionally filtered by status.
  Future<TaskListResponse> fetchTasks({
    TaskFilter filter = TaskFilter.all,
    int limit = 100,
    int offset = 0,
  }) async {
    final query = <String, String>{
      'status': filter.apiValue,
      'limit': limit.toString(),
      'offset': offset.toString(),
    };
    final json = await _apiClient.getJson('/tasks', queryParameters: query);
    return TaskListResponse.fromJson(json);
  }

  /// Fetches full details for a single task.
  Future<TaskModel> fetchTask(String taskId) async {
    final json = await _apiClient.getJson('/tasks/$taskId');
    final taskPayload = json['task'] is Map<String, dynamic>
        ? json['task'] as Map<String, dynamic>
        : json;
    return TaskModel.fromJson(taskPayload);
  }

  /// Approves a task idempotently via `POST /tasks/{id}/approve`.
  Future<TaskModel?> approveTask(String taskId) async {
    final json = await _apiClient.postJson(
      '/tasks/$taskId/approve',
      idempotencyKey: 'approve-$taskId',
    );
    if (json['task'] is Map<String, dynamic>) {
      return TaskModel.fromJson(json['task'] as Map<String, dynamic>);
    }
    return null;
  }

  /// Rejects a task idempotently via `POST /tasks/{id}/reject` with optional reason.
  Future<TaskModel?> rejectTask(String taskId, {String? reason}) async {
    final trimmed = reason?.trim();
    final json = await _apiClient.postJson(
      '/tasks/$taskId/reject',
      body: (trimmed != null && trimmed.isNotEmpty) ? {'reason': trimmed} : {},
      idempotencyKey: 'reject-$taskId',
    );
    if (json['task'] is Map<String, dynamic>) {
      return TaskModel.fromJson(json['task'] as Map<String, dynamic>);
    }
    return null;
  }

  /// Updates task status directly (e.g., rolling back to pending) via `PATCH /tasks/{id}`.
  Future<TaskModel?> updateTaskStatus(String taskId, TaskStatus status) async {
    final json = await _apiClient.patchJson(
      '/tasks/$taskId',
      body: {'status': status.apiValue},
    );
    if (json['task'] is Map<String, dynamic>) {
      return TaskModel.fromJson(json['task'] as Map<String, dynamic>);
    }
    return null;
  }

  /// Triggers an immediate Gmail invitation poll on the backend.
  Future<GmailSyncSummary> syncGmail() async {
    final json = await _apiClient.postJson('/tasks/sync');
    return GmailSyncSummary.fromJson(json);
  }
}
