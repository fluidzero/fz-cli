"""FZClient: authenticated httpx wrapper with auto-refresh and retry."""

from __future__ import annotations

import os
import random
import sys
import time
from typing import Any

import click
import httpx

from .auth.credentials import load_credentials
from .auth.m2m import exchange_client_credentials
from .auth.token import TokenManager
from .constants import EXIT_AUTH_FAILURE
from .errors import handle_api_error, handle_network_error

_TRANSIENT_STATUSES = {429, 502, 503, 504}
_MAX_TRANSIENT_RETRIES = 3


def _transient_delay(attempt: int) -> float:
    """Exponential backoff with jitter for transient failures."""
    base_delays = [1, 2, 4]
    base = base_delays[attempt] if attempt < len(base_delays) else base_delays[-1] * (2 ** (attempt - len(base_delays) + 1))
    return min(base + random.random(), 30.0)


class FZClient:
    """Sync HTTP client with automatic token management.

    Supports two auth modes:
    - **Browser (device flow)**: tokens from ``fz auth login``, refreshed
      via the backend's ``/oauth/token`` proxy.
    - **M2M (env vars)**: ``FZ_CLIENT_ID`` + ``FZ_CLIENT_SECRET`` exchanged
      for a short-lived JWT via ``/oauth/token``.  Re-exchanged automatically
      when expired (M2M tokens have no refresh token).
    """

    def __init__(self, api_url: str, verbose: bool = False) -> None:
        self.api_url = api_url.rstrip("/")
        self.verbose = verbose
        self._token_mgr = TokenManager(api_url)
        self._client = httpx.Client(base_url=self.api_url, timeout=60.0)
        self._resolved = False

        # M2M credentials (stored for re-exchange on expiry)
        self._m2m_client_id: str | None = None
        self._m2m_client_secret: str | None = None

    def _resolve_auth(self) -> None:
        """Resolve credentials on first use (lazy init)."""
        if self._resolved:
            return
        self._resolved = True

        # 1) Check env-var M2M credentials
        self._m2m_client_id = os.getenv("FZ_CLIENT_ID")
        self._m2m_client_secret = os.getenv("FZ_CLIENT_SECRET")

        if self._m2m_client_id and self._m2m_client_secret:
            self._exchange_m2m()
            return

        # 2) Load from credentials file (browser flow)
        if not self._token_mgr.load_from_credentials():
            click.echo("Error: Not authenticated. Run `fz auth login` first.", err=True)
            sys.exit(EXIT_AUTH_FAILURE)

    def _exchange_m2m(self) -> None:
        """Exchange M2M client credentials for a fresh access token."""
        tokens = exchange_client_credentials(
            self.api_url, self._m2m_client_id, self._m2m_client_secret,
        )
        self._token_mgr.set_tokens(
            access_token=tokens["access_token"],
            refresh_token=None,
            expires_in=tokens.get("expires_in", 3600),
        )

    @property
    def _is_m2m(self) -> bool:
        return bool(self._m2m_client_id and self._m2m_client_secret)

    def _headers(self) -> dict[str, str]:
        self._resolve_auth()
        token = self._token_mgr.get_access_token()

        # M2M tokens have no refresh token — re-exchange credentials on expiry
        if not token and self._is_m2m:
            self._exchange_m2m()
            token = self._token_mgr.get_access_token()

        if not token:
            click.echo("Error: No valid access token. Run `fz auth login`.", err=True)
            sys.exit(EXIT_AUTH_FAILURE)
        return {"Authorization": f"Bearer {token}"}

    def _log_request(self, method: str, url: str) -> None:
        if self.verbose:
            click.echo(f"  {method} {url}", err=True)

    def _retry_auth(self) -> bool:
        """Attempt to recover auth — refresh (browser) or re-exchange (M2M)."""
        if self._is_m2m:
            try:
                self._exchange_m2m()
                return True
            except (httpx.RequestError, click.ClickException) as exc:
                if self.verbose:
                    click.echo(f"  Auth re-exchange failed: {exc}", err=True)
                return False
        return self._token_mgr.refresh()

    def request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        data: Any = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """Make an authenticated API request with auto-retry on transient errors and 401."""
        self._log_request(method, f"{self.api_url}{path}")

        resp = None
        for attempt in range(_MAX_TRANSIENT_RETRIES):
            try:
                resp = self._client.request(
                    method,
                    path,
                    headers=self._headers(),
                    json=json,
                    data=data,
                    params=params,
                )
            except httpx.RequestError as exc:
                if attempt == _MAX_TRANSIENT_RETRIES - 1:
                    handle_network_error(exc)
                if self.verbose:
                    click.echo(
                        f"  Retry {attempt + 1}/{_MAX_TRANSIENT_RETRIES} ({type(exc).__name__})",
                        err=True,
                    )
                time.sleep(_transient_delay(attempt))
                continue

            # Transient server errors: retry with backoff
            if resp.status_code in _TRANSIENT_STATUSES and attempt < _MAX_TRANSIENT_RETRIES - 1:
                delay = _transient_delay(attempt)
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    try:
                        delay = max(delay, float(retry_after))
                    except ValueError:
                        pass
                if self.verbose:
                    click.echo(
                        f"  Retry {attempt + 1}/{_MAX_TRANSIENT_RETRIES} (HTTP {resp.status_code})",
                        err=True,
                    )
                time.sleep(delay)
                continue

            break

        # Retry once on 401 — refresh or re-exchange, then replay
        if resp.status_code == 401:
            www_auth = resp.headers.get("www-authenticate", "").lower()
            if "revoked" not in www_auth and self._retry_auth():
                try:
                    resp = self._client.request(
                        method,
                        path,
                        headers=self._headers(),
                        json=json,
                        data=data,
                        params=params,
                    )
                except httpx.RequestError as exc:
                    handle_network_error(exc)

        # Check for errors
        if resp.status_code >= 400:
            handle_api_error(resp)

        return resp

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()

    def raw_client(self) -> httpx.Client:
        """Return the underlying httpx.Client for direct S3 uploads etc."""
        return self._client
