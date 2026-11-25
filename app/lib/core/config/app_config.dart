/// Runtime configuration for the app.
class AppConfig {
  /// Base URL for FastAPI backend (http://localhost:8000 for dev, https://render.com for prod).
  final String apiBaseUrl;

  /// Whether to enable debug logging.
  final bool debugMode;

  const AppConfig({
    required this.apiBaseUrl,
    this.debugMode = false,
  });

  /// Factory constructor to load from environment or defaults.
  factory AppConfig.fromEnvironment() {
    final apiBaseUrl = String.fromEnvironment(
      'API_BASE_URL',
      defaultValue: 'http://localhost:8000',
    );

    return AppConfig(
      apiBaseUrl: apiBaseUrl,
      debugMode: bool.fromEnvironment('DEBUG_MODE', defaultValue: false),
    );
  }
}
