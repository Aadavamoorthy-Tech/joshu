import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;
import 'package:material_ui/material_ui.dart';

const apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://localhost:8000',
);

void main() {
  runApp(const ChiefOfStaffApp());
}

class ChiefOfStaffApp extends StatelessWidget {
  const ChiefOfStaffApp({super.key, this.client});

  final http.Client? client;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Personal AI Chief of Staff',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.indigo),
      ),
      home: HomePage(client: client),
    );
  }
}

class HomePage extends StatefulWidget {
  const HomePage({super.key, this.client});

  final http.Client? client;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  late final http.Client _client = widget.client ?? http.Client();
  bool _checking = true;
  String? _error;

  @override
  void initState() {
    super.initState();
    _checkBackend();
  }

  Future<void> _checkBackend() async {
    setState(() {
      _checking = true;
      _error = null;
    });

    String? error;
    try {
      final base = Uri.parse(apiBaseUrl);
      if (!base.hasAuthority || !['http', 'https'].contains(base.scheme)) {
        throw const FormatException('API_BASE_URL must be an HTTP(S) URL.');
      }
      final response = await _client
          .get(
            base.replace(
              path: '${base.path.replaceAll(RegExp(r'/$'), '')}/health',
            ),
          )
          .timeout(const Duration(seconds: 10));
      if (response.statusCode != 200) {
        throw FormatException('Server returned HTTP ${response.statusCode}.');
      }
      final body = jsonDecode(response.body);
      if (body is! Map || body['status'] != 'ok') {
        throw const FormatException('Unexpected health response.');
      }
    } on TimeoutException {
      error = 'The server did not respond in time.';
    } on http.ClientException catch (exception) {
      error = 'Could not reach the server: ${exception.message}';
    } on FormatException catch (exception) {
      error = exception.message;
    }

    if (!mounted) return;
    setState(() {
      _checking = false;
      _error = error;
    });
  }

  @override
  void dispose() {
    if (widget.client == null) _client.close();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Personal AI Chief of Staff')),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Getting started',
                  style: Theme.of(context).textTheme.headlineMedium,
                ),
                const SizedBox(height: 16),
                const Text(
                  'Google sign-in, meeting invitations, and approvals are not available yet.',
                ),
                const SizedBox(height: 24),
                if (_checking)
                  const Text('Checking server connection...')
                else if (_error == null)
                  const Text('Server connected')
                else ...[
                  Text('Server unavailable: $_error'),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    onPressed: _checkBackend,
                    child: const Text('Retry'),
                  ),
                ],
              ],
            ),
          ),
        ),
      ),
    );
  }
}
