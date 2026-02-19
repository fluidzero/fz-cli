"""Token lifecycle management: load, expiry check, refresh, decode."""

from __future__ import annotations

import random
import time
from typing import Any

import click
import httpx
import jwt

from .credentials import load_credentials, save_credentials

_MAX_REFRESH_RETRIES = 3
_TRANSIENT_STATUSES = {429, 502, 503, 504}


def _retry_delay(attempt: int) -> float:
    """Exponential backoff with jitter."""
    base_delays = [1, 2, 4]
    base = base_delays[attempt] if attempt < len(base_delays) else base_delays[-1]
    return min(base + random.random(), 30.0)


class TokenManager:
    """Manages access/refresh token lifecycle.

    Refresh goes through the backend's ``/oauth/token`` proxy with
    ``source=device`` so the proxy routes to the correct WorkOS endpoint
    (User Management for device-flow tokens, AuthKit OAuth2 for others).
    """

    def __init__(self, api_url: str) -> None:
        self.api_url = api_url
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: int = 0
        self._client_id: str | None = None

    # ── Load / Save ─────────────────────────────────────────────────────

    def load_from_credentials(self) -> bool:
        """Load tokens from credentials file. Returns True if loaded."""
        creds = load_credentials()
        if not creds:
            return False
        self._access_token = creds["access_token"]
        self._refresh_token = creds.get("refresh_token")
        self._expires_at = creds.get("expires_at", 0)
        self._client_id = creds.get("client_id")
        if creds.get("api_url"):
            self.api_url = creds["api_url"]
        return True

    def set_tokens(
        self,
        access_token: str,
        refresh_token: str | None,
        expires_in: int,
        client_id: str | None = None,
    ) -> None:
        """Set tokens after a fresh login."""
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at = int(time.time()) + expires_in
        if client_id:
            self._client_id = client_id

        save_credentials(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=self._expires_at,
            api_url=self.api_url,
            client_id=self._client_id,
        )

    # ── Expiry / Access ─────────────────────────────────────────────────

    def is_expired(self) -> bool:
        """Check if the access token is expired or will expire within 60s."""
        return self._expires_at - 60 < int(time.time())

    def get_access_token(self) -> str | None:
        """Return a valid access token, refreshing transparently if needed."""
        if not self._access_token:
            return None
        if self.is_expired():
            if self._refresh_token:
                self.refresh()
            else:
                return None
        return self._access_token

    # ── Refresh ─────────────────────────────────────────────────────────

    def refresh(self) -> bool:
        """Refresh the access token via the backend's /oauth/token proxy.

        The proxy handles routing to the correct WorkOS endpoint based on
        the ``source=device`` hint (User Management for CLI device-flow
        tokens, AuthKit OAuth2 for Swagger/frontend tokens).

        Returns True on success, False on failure.
        """
        if not self._refresh_token:
            return False

        resp = None
        with httpx.Client(timeout=30.0) as client:
            for attempt in range(_MAX_REFRESH_RETRIES):
                try:
                    resp = client.post(
                        f"{self.api_url}/oauth/token",
                        data={
                            "grant_type": "refresh_token",
                            "refresh_token": self._refresh_token,
                            "source": "device",
                        },
                    )
                except httpx.RequestError as exc:
                    if attempt == _MAX_REFRESH_RETRIES - 1:
                        click.echo(f"Warning: Token refresh failed (network): {exc}", err=True)
                        return False
                    time.sleep(_retry_delay(attempt))
                    continue

                if resp.status_code not in _TRANSIENT_STATUSES or attempt == _MAX_REFRESH_RETRIES - 1:
                    break
                time.sleep(_retry_delay(attempt))

        if resp is None or resp.status_code != 200:
            click.echo(
                "Warning: Token refresh failed. "
                "Run `fz auth login` if requests fail.",
                err=True,
            )
            return False

        try:
            body = resp.json()
        except ValueError:
            click.echo("Warning: Token refresh returned invalid response.", err=True)
            return False

        access_token = body.get("access_token")
        if not access_token:
            click.echo("Warning: Token refresh response missing access_token.", err=True)
            return False

        self._access_token = access_token
        # WorkOS rotates the refresh token on each use
        self._refresh_token = body.get("refresh_token", self._refresh_token)
        # Derive expiry: prefer expires_in from response, else decode JWT exp
        expires_in = body.get("expires_in")
        if expires_in:
            self._expires_at = int(time.time()) + expires_in
        else:
            claims = self._decode(self._access_token)
            self._expires_at = claims.get("exp", int(time.time()) + 300)

        save_credentials(
            access_token=self._access_token,
            refresh_token=self._refresh_token,
            expires_at=self._expires_at,
            api_url=self.api_url,
            client_id=self._client_id,
        )
        return True

    # ── JWT helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _decode(token: str) -> dict[str, Any]:
        try:
            return jwt.decode(token, options={"verify_signature": False}, algorithms=["RS256"])
        except jwt.PyJWTError:
            return {}

    def decode_claims(self) -> dict[str, Any]:
        """Decode JWT claims without verification (for display purposes)."""
        if not self._access_token:
            return {}
        return self._decode(self._access_token)

    @property
    def has_tokens(self) -> bool:
        return self._access_token is not None
