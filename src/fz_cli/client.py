"""FZClient: authenticated httpx wrapper with auto-refresh and retry."""

from __future__ import annotations

import os
import sys
from typing import Any

import click
import httpx

from .auth.credentials import load_credentials
from .auth.m2m import exchange_client_credentials
from .auth.token import TokenManager
from .constants import EXIT_AUTH_FAILURE
from .errors import handle_api_error, handle_network_error


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
            except Exception:
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
        """Make an authenticated API request with auto-retry on 401."""
        self._log_request(method, f"{self.api_url}{path}")

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
            return None  # unreachable

        # Retry once on 401 — refresh or re-exchange, then replay
        if resp.status_code == 401:
            www_auth = resp.headers.get("www-authenticate", "").lower()
            if "revoked" in www_auth:
                pass  # fall through to handle_api_error
            elif self._retry_auth():
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
