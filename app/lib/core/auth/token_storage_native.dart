/// Mobile & Windows implementation backed by OS keychains via flutter_secure_storage.
/// - Android: EncryptedSharedPreferences + Android Keystore (AES-GCM).
/// - Windows: Windows Credential Manager / DPAPI (CredWrite / CredRead).

import 'package:flutter_secure_storage/flutter_secure_storage';
import 'token_storage_adapter.dart';

class NativeSecureStorageAdapter implements TokenStorageAdapter {
  final FlutterSecureStorage _storage;

  NativeSecureStorageAdapter({FlutterSecureStorage? storage})
      : _storage = storage ??
            const FlutterSecureStorage(
              aOptions: AndroidOptions(encryptedSharedPreferences: true),
            );

  @override
  Future<String?> read(String key) async {
    try {
      return await _storage.read(key: key);
    } on Exception {
      /// Android Keystore corruption can occur after device backup/restore.
      /// Clear storage and degrade gracefully to sign-in screen.
      await _storage.deleteAll();
      return null;
    }
  }

  @override
  Future<void> write(String key, String value) async {
    await _storage.write(key: key, value: value);
  }

  @override
  Future<void> delete(String key) async {
    await _storage.delete(key: key);
  }
}
