"""Encryption utilities for storing sensitive tokens."""

import os
from cryptography.fernet import Fernet

# Generate or load encryption key from environment
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")

if not ENCRYPTION_KEY:
    # Generate a new key (save this in .env for production)
    ENCRYPTION_KEY = Fernet.generate_key().decode()
    print(f"⚠️  No ENCRYPTION_KEY found. Generated new key:\n{ENCRYPTION_KEY}\nAdd this to .env as ENCRYPTION_KEY")

cipher = Fernet(ENCRYPTION_KEY.encode())


def encrypt_token(token: str) -> bytes:
    """Encrypt a token."""
    return cipher.encrypt(token.encode())


def decrypt_token(encrypted_token: bytes) -> str:
    """Decrypt a token."""
    return cipher.decrypt(encrypted_token).decode()
