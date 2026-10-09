"""Envelope encryption for OAuth tokens and provider secrets (AES-256-GCM, KEK from BOTWOK_MASTER_KEY)."""
from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import settings

KEY_VERSION = 1


def _kek() -> bytes:
    raw = settings.botwok_master_key.encode()
    try:
        decoded = base64.urlsafe_b64decode(raw + b"=" * (-len(raw) % 4))
        if len(decoded) == 32:
            return decoded
    except Exception:
        pass
    return hashlib.sha256(raw).digest()  # derive 32 bytes from any string (local dev)


@dataclass(frozen=True)
class Sealed:
    ciphertext: bytes
    nonce: bytes
    key_version: int


def seal(plaintext: str, aad: str = "") -> Sealed:
    nonce = os.urandom(12)
    ct = AESGCM(_kek()).encrypt(nonce, plaintext.encode(), aad.encode() or None)
    return Sealed(ct, nonce, KEY_VERSION)


def unseal(ciphertext: bytes, nonce: bytes, key_version: int = KEY_VERSION, aad: str = "") -> str:
    if key_version != KEY_VERSION:
        raise ValueError(f"unsupported key_version {key_version}")
    return AESGCM(_kek()).decrypt(nonce, ciphertext, aad.encode() or None).decode()
