"""OAuth Device Authorization flow for CLI authentication.

Uses the WorkOS Device Authorization flow (RFC 8628):
1. Request device + user codes from WorkOS
2. User confirms in browser
3. CLI polls for tokens
"""

from __future__ import annotations

import time
import webbrowser
from typing import Any

import click
import httpx


# WorkOS User Management endpoints (first-party CLI auth)
_DEVICE_AUTH_URL = "https://api.workos.com/user_management/authorize/device"
_TOKEN_URL = "https://api.workos.com/user_management/authenticate"


def browser_login(
    api_url: str,
    authkit_subdomain: str,
    oauth_client_id: str,
) -> dict[str, Any]:
    """Run the WorkOS Device Authorization flow.

    Returns dict with access_token, refresh_token.
    Raises click.ClickException on failure.
    """
    if not oauth_client_id:
        raise click.ClickException(
            "OAuth client ID not configured. "
            "Set FZ_OAUTH_CLIENT_ID env var or oauth_client_id in config.toml."
        )

    # Step 1: Request device authorization
    with httpx.Client(timeout=30.0) as client:
        resp = client.post(
            _DEVICE_AUTH_URL,
            data={"client_id": oauth_client_id},
        )

    if resp.status_code != 200:
        try:
            err = resp.json()
            msg = err.get("message", err.get("error", resp.text))
        except Exception:
            msg = resp.text
        raise click.ClickException(f"Device authorization failed: {msg}")

    device_data = resp.json()
    device_code = device_data["device_code"]
    user_code = device_data["user_code"]
    verification_uri = device_data.get("verification_uri", "")
    verification_uri_complete = device_data.get("verification_uri_complete", "")
    expires_in = device_data.get("expires_in", 300)
    poll_interval = device_data.get("interval", 5)

    # Step 2: Show user code and open browser
    click.echo(f"\nYour confirmation code: {user_code}\n", err=True)

    open_url = verification_uri_complete or verification_uri
    if open_url:
        click.echo(f"Opening browser to confirm...", err=True)
        click.echo(f"If the browser doesn't open, visit:\n  {open_url}\n", err=True)
        webbrowser.open(open_url)
    else:
        click.echo(f"Visit the URL shown above and enter the code.", err=True)

    # Step 3: Poll for tokens
    click.echo("Waiting for confirmation...", err=True)
    deadline = time.monotonic() + expires_in

    with httpx.Client(timeout=30.0) as client:
        while time.monotonic() < deadline:
            time.sleep(poll_interval)

            resp = client.post(
                _TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "device_code": device_code,
                    "client_id": oauth_client_id,
                },
            )

            if resp.status_code == 200:
                token_data = resp.json()
                # WorkOS returns access_token and refresh_token at top level
                if "access_token" in token_data:
                    return token_data

                # Some responses nest the token differently
                raise click.ClickException(
                    "Unexpected token response format. "
                    "Please report this issue."
                )

            # Handle polling errors
            try:
                err_body = resp.json()
                error_code = err_body.get("error", err_body.get("code", ""))
            except Exception:
                error_code = ""

            if error_code == "authorization_pending":
                continue
            elif error_code == "slow_down":
                poll_interval += 1
                continue
            elif error_code in ("access_denied", "expired_token"):
                msg = err_body.get("error_description", err_body.get("message", error_code))
                raise click.ClickException(f"Authentication failed: {msg}")
            else:
                # Unknown error — keep polling unless it's a hard failure
                if resp.status_code >= 400 and resp.status_code != 428:
                    msg = err_body.get("error_description", err_body.get("message", resp.text))
                    raise click.ClickException(f"Authentication failed: {msg}")
                continue

    raise click.ClickException(
        f"Authentication timed out after {expires_in}s. "
        "Try again with `fz auth login`."
    )
