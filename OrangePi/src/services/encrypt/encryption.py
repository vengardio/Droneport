import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_PATH = Path(__file__).parent / "aes_key.bin"


def load_aesgcm(path: Path = KEY_PATH) -> AESGCM:
    key = Path(path).read_bytes()
    if len(key) != 32:
        raise ValueError(f"AES key must be 32 bytes, got {len(key)}")
    return AESGCM(key)


def encrypt_packet(aesgcm: AESGCM, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, plaintext, None)


def decrypt_packet(aesgcm: AESGCM, data: bytes) -> bytes:
    if len(data) < 28:
        raise ValueError(f"Too short to decrypt: {len(data)} bytes")
    return aesgcm.decrypt(data[:12], data[12:], None)
