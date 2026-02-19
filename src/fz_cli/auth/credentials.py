"""Read/write ~/.config/fluidzero/credentials.json (mode 0600)."""

from __future__ import annotations

import json
import os
from typing import Any

from ..constants import CREDENTIALS_PATH


def load_credentials() -> dict[str, Any] | None:
    """Return stored credentials dict, or None if absent/corrupt."""
    if not CREDENTIALS_PATH.is_file():
        return None
    try:
        data = json.loads(CREDENTIALS_PATH.read_text())
        if not isinstance(data, dict) or "access_token" not in data:
            return None
        return data
    except (json.JSONDecodeError, OSError):
        return None


def save_credentials(
    *,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: int,
    api_url: str,
    client_id: str | None = None,
) -> None:
    """Persist credentials to disk with restrictive permissions."""
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any] = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "api_url": api_url,
    }
    if client_id:
        payload["client_id"] = client_id

    # Write atomically-ish: write then chmod
    CREDENTIALS_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    os.chmod(CREDENTIALS_PATH, 0o600)


def delete_credentials() -> bool:
    """Remove the credentials file. Returns True if deleted."""
    if CREDENTIALS_PATH.is_file():
        CREDENTIALS_PATH.unlink()
        return True
    return False
