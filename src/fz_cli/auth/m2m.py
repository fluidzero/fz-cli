"""M2M client_credentials exchange."""

from __future__ import annotations

import random
import time
from typing import Any

import click
import httpx

_MAX_RETRIES = 3
_TRANSIENT_STATUSES = {429, 502, 503, 504}


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter."""
    base_delays = [1, 2, 4]
    base = base_delays[attempt] if attempt < len(base_delays) else base_delays[-1]
    return min(base + random.random(), 30.0)


def exchange_client_credentials(
    api_url: str,
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """Exchange M2M client credentials for an access token.

    Returns dict with access_token, expires_in.
    Raises click.ClickException on failure.
    """
    resp = None
    with httpx.Client(timeout=30.0) as client:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = client.post(
                    f"{api_url}/oauth/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": client_id,
                        "client_secret": client_secret,
                    },
                )
            except httpx.RequestError as exc:
                if attempt == _MAX_RETRIES - 1:
                    raise click.ClickException(
                        f"M2M authentication failed: network error: {exc}"
                    ) from exc
                time.sleep(_retry_delay(attempt))
                continue

            if resp.status_code not in _TRANSIENT_STATUSES or attempt == _MAX_RETRIES - 1:
                break
            time.sleep(_retry_delay(attempt))

    if resp is None or resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error_description", err.get("error", resp.text))
        except ValueError:
            msg = resp.text if resp else "no response"
        raise click.ClickException(f"M2M authentication failed: {msg}")

    body = resp.json()
    if "access_token" not in body:
        raise click.ClickException("M2M authentication failed: response missing access_token")

    return body
