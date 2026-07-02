"""M2M auth mode must never write to the browser-flow credentials file.

Regression (found live 2026-07-02): running any command with FZ_CLIENT_ID/
FZ_CLIENT_SECRET set persisted the short-lived M2M token to
~/.config/fluidzero/credentials.json, overwriting the user's device-flow
refresh token (WorkOS rotates refresh tokens, so this is unrecoverable
without a re-login).
"""

from __future__ import annotations

import httpx

from fz_cli.client import FZClient


def test_m2m_exchange_does_not_persist_credentials(monkeypatch):
    monkeypatch.setenv("FZ_CLIENT_ID", "client_ci")
    monkeypatch.setenv("FZ_CLIENT_SECRET", "s3cret")

    saved = []
    monkeypatch.setattr(
        "fz_cli.auth.token.save_credentials",
        lambda **kw: saved.append(kw),
    )
    monkeypatch.setattr(
        "fz_cli.client.exchange_client_credentials",
        lambda *a, **kw: {"access_token": "m2m-tok", "expires_in": 3600},
    )

    def handler(req):
        assert req.headers["authorization"] == "Bearer m2m-tok"
        return httpx.Response(200, json=[])

    fz = FZClient("http://ev.test")
    fz._client = httpx.Client(base_url="http://ev.test", transport=httpx.MockTransport(handler))
    resp = fz.get("/api/projects")

    assert resp.status_code == 200
    assert saved == [], "M2M token exchange must not write the credentials file"


def test_browser_login_still_persists(monkeypatch):
    """The interactive login path keeps persisting (persist defaults to True)."""
    from fz_cli.auth.token import TokenManager

    saved = []
    monkeypatch.setattr(
        "fz_cli.auth.token.save_credentials",
        lambda **kw: saved.append(kw),
    )
    tm = TokenManager("http://ev.test")
    tm.set_tokens(access_token="user-tok", refresh_token="rt", expires_in=300)
    assert len(saved) == 1
    assert saved[0]["refresh_token"] == "rt"


def test_m2m_exchange_failure_exits_auth_code(monkeypatch):
    """A dead/revoked key must exit 2 (auth), not 1 (general)."""
    import click
    import pytest

    from fz_cli.auth.m2m import exchange_client_credentials

    class FakeResp:
        status_code = 401

        def json(self):
            return {"error": "unauthorized"}

        @property
        def text(self):
            return "unauthorized"

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **kw):
            return FakeResp()

    monkeypatch.setattr("fz_cli.auth.m2m.httpx.Client", lambda **kw: FakeClient())
    with pytest.raises(click.ClickException) as exc:
        exchange_client_credentials("http://ev.test", "client_x", "bad")
    assert exc.value.exit_code == 2
