"""Symmetric encryption for model API keys. Keys are never returned by any API."""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from .config import get_settings


@lru_cache
def _fernet() -> Fernet:
    return Fernet(get_settings().secret_key())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode()


def mask(plain: str) -> str:
    """Show only the last four characters."""
    return f"****{plain[-4:]}" if len(plain) > 4 else "****"


def redact(text: str, secrets_: list[str]) -> str:
    for s in secrets_:
        if s:
            text = text.replace(s, "***")
    return text
