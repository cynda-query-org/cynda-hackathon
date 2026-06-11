"""Credential encryption/decryption using Fernet (AES-128-CBC + HMAC-SHA256).

Encrypted credentials are stored as {"_enc": "<fernet_token>"} so the
database column stays JSONB-compatible (Metabase, pg operators all work).

Set CREDENTIALS_ENCRYPTION_KEY to a Fernet key in the environment.
Generate one with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

If the key is absent, credentials are stored as plaintext JSON.
"""
import json
import logging
import os

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet | None:
    key = os.environ.get("CREDENTIALS_ENCRYPTION_KEY", "").strip()
    if not key:
        logger.warning("CREDENTIALS_ENCRYPTION_KEY not set — credentials stored in plaintext")
        return None
    return Fernet(key.encode())


def encrypt_credentials(data: dict) -> str:
    """Return a JSON string safe to store in a JSONB column."""
    f = _get_fernet()
    if f is None:
        return json.dumps(data)
    token = f.encrypt(json.dumps(data).encode()).decode()
    return json.dumps({"_enc": token})


def decrypt_credentials(stored) -> dict | None:
    if not stored:
        return None
    # psycopg2 auto-parses JSONB columns and returns a dict directly
    if isinstance(stored, dict):
        parsed = stored
    else:
        try:
            parsed = json.loads(stored)
        except json.JSONDecodeError:
            # Old format: bare Fernet token written as TEXT (PR #47 transitional rows)
            f = _get_fernet()
            if f is None:
                return None
            try:
                return json.loads(f.decrypt(stored.encode()))
            except InvalidToken:
                return None
    if "_enc" not in parsed:
        return parsed  # plaintext row — no key set when it was saved
    f = _get_fernet()
    if f is None:
        return None
    try:
        return json.loads(f.decrypt(parsed["_enc"].encode()))
    except InvalidToken:
        return None
