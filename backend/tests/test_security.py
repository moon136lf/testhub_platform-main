"""Security helper tests (AES-GCM via pycryptodome)."""
import base64

import pytest
from app.core.security import encrypt_value, decrypt_value, derive_key


def test_encrypt_decrypt_roundtrip():
    plain = "sk-xxxxxxxxxxxxxxxxxxxxxxxx"
    cipher = encrypt_value(plain)
    assert cipher != plain
    assert decrypt_value(cipher) == plain


def test_encrypt_different_each_call():
    """AES-GCM 随机 nonce，同一明文两次密文不同。"""
    a = encrypt_value("same-secret")
    b = encrypt_value("same-secret")
    assert a != b
    assert decrypt_value(a) == decrypt_value(b) == "same-secret"


def test_derive_key_stable_from_secret():
    """同 secret 派生同 key（PBKDF2 确定性）。"""
    k1 = derive_key("my-jwt-secret")
    k2 = derive_key("my-jwt-secret")
    assert k1 == k2
    assert len(k1) == 32  # AES-256


def test_decrypt_invalid_cipher_raises():
    with pytest.raises(ValueError):
        decrypt_value("not-a-valid-cipher")


def test_tampered_ciphertext_rejected():
    """GCM tag verification: flipping a ciphertext byte must raise."""
    cipher = encrypt_value("secret-value")
    blob = base64.b64decode(cipher)
    # flip a byte in the ciphertext region (between nonce[12] and tag[-16])
    tampered = bytearray(blob)
    tampered[20] ^= 0x01  # flip one byte in the ciphertext area
    tampered_blob = base64.b64encode(bytes(tampered)).decode("ascii")
    with pytest.raises(Exception):
        decrypt_value(tampered_blob)
