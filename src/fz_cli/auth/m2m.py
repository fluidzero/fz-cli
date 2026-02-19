"""M2M client_credentials exchange."""

from __future__ import annotations

from typing import Any

import click
import httpx


def exchange_client_credentials(
    api_url: str,
    client_id: str,
    client_secret: str,
) -> dict[str, Any]:
    """Exchange M2M client credentials for an access token.

    Returns dict with access_token, expires_in.
    Raises click.ClickException on failure.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(
                f"{api_url}/oauth/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
    except httpx.RequestError as exc:
        raise click.ClickException(f"M2M authentication failed: network error: {exc}") from exc

    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("error_description", err.get("error", resp.text))
        except Exception:
            msg = resp.text
        raise click.ClickException(f"M2M authentication failed: {msg}")

    return resp.json()
