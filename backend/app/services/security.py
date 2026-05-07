"""Fernet-based field-level encryption for sensitive asset amounts."""
import struct
from cryptography.fernet import Fernet

from app.config import settings


def _fernet() -> Fernet:
    return Fernet(settings.ASSET_ENCRYPTION_KEY.encode())


def encrypt_amount(amount: float) -> bytes:
    raw = struct.pack("d", amount)
    return _fernet().encrypt(raw)


def decrypt_amount(data: bytes) -> float:
    raw = _fernet().decrypt(data)
    return struct.unpack("d", raw)[0]
