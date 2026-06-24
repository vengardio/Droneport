"""
AES-256-GCM шифрование/расшифровка UDP-пакетов.

Формат зашифрованного пакета:
    [nonce 12 байт] + [ciphertext + tag 16 байт]

Использование:
    from src.encrypt.encryption import load_aesgcm, encrypt_packet, decrypt_packet

    aesgcm = load_aesgcm()                    # один раз при старте
    encrypted = encrypt_packet(aesgcm, raw)   # перед отправкой
    plain     = decrypt_packet(aesgcm, data)  # после приёма
"""
import os
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_PATH = Path(__file__).parent / "aes_key.bin"


def load_aesgcm(path: Path = KEY_PATH) -> AESGCM:
    key = Path(path).read_bytes()
    if len(key) != 32:
        raise ValueError(f"AES key must be exactly 32 bytes, got {len(key)}: {path}")
    return AESGCM(key)


def encrypt_packet(aesgcm: AESGCM, plaintext: bytes) -> bytes:
    nonce = os.urandom(12)
    return nonce + aesgcm.encrypt(nonce, plaintext, None)


def decrypt_packet(aesgcm: AESGCM, data: bytes) -> bytes:
    if len(data) < 28:  # 12 nonce + 0 payload + 16 tag = минимум
        raise ValueError(f"Packet too short to decrypt: {len(data)} bytes")
    return aesgcm.decrypt(data[:12], data[12:], None)
