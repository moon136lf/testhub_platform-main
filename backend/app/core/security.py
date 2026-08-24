"""
Symmetric encryption for secrets stored in system_setting / test_env.

Uses AES-256-GCM via pycryptodome. Key derived once from JWT_SECRET_KEY
(PBKDF2-HMAC-SHA256, 32 bytes) so no new config key is needed.
"""
import base64
import hashlib
import os

from Crypto.Cipher import AES

from app.core.config import settings

# Fixed salt (not secret; security comes from JWT_SECRET_KEY being private in prod).
_SALT = b"moontest-system-settings-salt"
_PBKDF2_ITER = 100_000


def derive_key(secret: str) -> bytes:
    """Derive a 32-byte AES key from a passphrase via PBKDF2."""
    return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), _SALT, _PBKDF2_ITER, dklen=32)


def _key() -> bytes:
    # NOTE: the encryption key is derived from JWT_SECRET_KEY. Rotating that secret
    # (a common ops practice) renders all previously encrypted DB secrets undecryptable.
    # If secret rotation is needed, add a dedicated ENCRYPTION_KEY setting and migrate.
    return derive_key(settings.JWT_SECRET_KEY)


def encrypt_value(plain: str) -> str:
    """Encrypt a plaintext string. Returns base64(nonce + ciphertext + tag)."""
    nonce = os.urandom(12)
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    ct, tag = cipher.encrypt_and_digest(plain.encode("utf-8"))
    blob = nonce + ct + tag
    return base64.b64encode(blob).decode("ascii")


def decrypt_value(token: str) -> str:
    """Decrypt a value produced by encrypt_value. Raises on tamper / bad input."""
    blob = base64.b64decode(token)
    nonce, ct, tag = blob[:12], blob[12:-16], blob[-16:]
    cipher = AES.new(_key(), AES.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ct, tag).decode("utf-8")
