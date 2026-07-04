"""Symmetric encryption for at-rest storage of sensitive credentials
(LLM API keys, social account tokens, CRM keys, etc.).
"""
import os
import base64
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent / ".env")


def _get_fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY")
    if not key:
        raise RuntimeError("FERNET_KEY missing from environment")
    # accept url-safe base64 keys of 32 bytes
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt(plaintext: str) -> str:
    if plaintext is None:
        return ""
    token = _get_fernet().encrypt(plaintext.encode("utf-8"))
    return token.decode("utf-8")


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def mask(value: str) -> str:
    """Return a display-safe masked view of a secret."""
    if not value:
        return ""
    if len(value) <= 8:
        return "•" * len(value)
    return f"{value[:4]}{'•' * 8}{value[-4:]}"
