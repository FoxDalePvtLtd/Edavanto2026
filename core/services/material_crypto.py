"""
AES-256-GCM encryption for lesson study material.

Design:
  - Per-file random 12-byte nonce, stored in LessonMaterial.encryption_nonce.
  - File format on disk:
        [ 12-byte nonce ][ ciphertext ][ 16-byte GCM tag ]
  - The nonce column duplicates the first 12 bytes for indexing/rotation,
    but the authoritative nonce lives in the file header.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from typing import BinaryIO, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from django.conf import settings


NONCE_SIZE = 12
TAG_SIZE = 16


def _key_bytes() -> bytes:
    raw = settings.LESSON_MATERIAL_ENCRYPTION_KEY
    if isinstance(raw, bytes):
        raw = raw.decode("ascii")
    try:
        key = bytes.fromhex(raw)
    except ValueError:
        # Allow a raw 32-char string as fallback (dev only)
        key = raw.encode("utf-8")[:32].ljust(32, b"\0")
    if len(key) != 32:
        raise ValueError(
            "LESSON_MATERIAL_ENCRYPTION_KEY must be 32 bytes (64 hex chars)."
        )
    return key


def encrypt_stream(source: BinaryIO, dest: BinaryIO) -> Tuple[str, str, int]:
    """
    Encrypt `source` into `dest`.

    Returns (nonce_hex, plaintext_sha256_hex, plaintext_size_bytes).
    """
    aes = AESGCM(_key_bytes())
    nonce = secrets.token_bytes(NONCE_SIZE)

    plaintext = source.read()
    digest = hashlib.sha256(plaintext).hexdigest()
    size = len(plaintext)

    ciphertext_and_tag = aes.encrypt(nonce, plaintext, associated_data=None)

    dest.write(nonce)
    dest.write(ciphertext_and_tag)

    return nonce.hex(), digest, size


def decrypt_bytes(blob: bytes) -> bytes:
    """
    Decrypt a blob produced by `encrypt_stream`.
    Verifies the GCM tag; raises `cryptography.exceptions.InvalidTag` on tamper.
    """
    if len(blob) < NONCE_SIZE + TAG_SIZE:
        raise ValueError("Ciphertext too short.")

    aes = AESGCM(_key_bytes())
    nonce = blob[:NONCE_SIZE]
    ciphertext_and_tag = blob[NONCE_SIZE:]
    return aes.decrypt(nonce, ciphertext_and_tag, associated_data=None)