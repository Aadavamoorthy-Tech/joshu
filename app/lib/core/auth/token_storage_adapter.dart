/// Platform-agnostic secure key-value contract for session persistence.
abstract interface class TokenStorageAdapter {
  /// Reads the stored session JSON payload, or null if absent.
  Future<String?> read(String key);

  /// Persists the serialized session securely for the current platform.
  Future<void> write(String key, String value);

  /// Permanently removes the stored key (used on logout or corruption).
  Future<void> delete(String key);
}
