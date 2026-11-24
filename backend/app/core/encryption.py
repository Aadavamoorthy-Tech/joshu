"""Symmetric Fernet encryption utilities for persisting Google OAuth tokens at rest."""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

_DEV_FALLBACK_KEY: Optional[bytes] = None


def _resolve_fernet_key() -> bytes:
    """Resolve ENCRYPTION_KEY from environment or generate an ephemeral in-memory dev key."""
    global _DEV_FALLBACK_KEY
    raw_key = os.getenv("ENCRYPTION_KEY", "").strip()
    if raw_key and raw_key != "YOUR_FERNET_ENCRYPTION_KEY_HERE":
        return raw_key.encode("utf-8")

    # Never log or write ephemeral fallback keys to disk.
    if _DEV_FALLBACK_KEY is None:
        _DEV_FALLBACK_KEY = Fernet.generate_key()
    return _DEV_FALLBACK_KEY


@lru_cache(maxsize=4)
def _get_cipher(key: bytes) -> Fernet:
    return Fernet(key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a sensitive string and return a UTF-8 Fernet token string."""
    if not plaintext:
        raise ValueError("Cannot encrypt empty secret")
    cipher = _get_cipher(_resolve_fernet_key())
    return cipher.encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted token string."""
    if not ciphertext:
        raise ValueError("Cannot decrypt empty ciphertext")
    cipher = _get_cipher(_resolve_fernet_key())
    try:
        return cipher.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt stored credential with current ENCRYPTION_KEY") from exc
