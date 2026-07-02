"""Unit tests for FZClient.request — real retry/401 logic over MockTransport."""

from __future__ import annotations

import httpx
import pytest

from fz_cli.client import FZClient


@pytest.fixture
def make_client(monkeypatch):
    """Build an FZClient with mocked transport and pre-resolved auth."""

    def _make(handler):
        fz = FZClient("http://ev.test")
        fz._client = httpx.Client(base_url="http://ev.test", transport=httpx.MockTransport(handler))
        fz._resolved = True
        monkeypatch.setattr(fz._token_mgr, "get_access_token", lambda: "tok-1")
        monkeypatch.setattr("fz_cli.client.time.sleep", lambda s: None)
        return fz

    return _make


def test_transient_retry_then_success(make_client):
    calls = []

    def handler(req):
        calls.append(req)
        return httpx.Response(503) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    fz = make_client(handler)
    assert fz.get("/x").json() == {"ok": 1}
    assert len(calls) == 3


def test_retry_after_honored(make_client, monkeypatch):
    delays = []
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "9"})
        return httpx.Response(200, json={})

    fz = make_client(handler)
    # Patch AFTER make_client, which installs its own no-op sleep.
    monkeypatch.setattr("fz_cli.client.time.sleep", lambda s: delays.append(s))
    fz.get("/x")
    assert delays and delays[0] >= 9.0


def test_401_refresh_and_replay(make_client, monkeypatch):
    calls = []

    def handler(req):
        calls.append(req)
        if len(calls) == 1:
            return httpx.Response(401, headers={"WWW-Authenticate": "Bearer"})
        return httpx.Response(200, json={"ok": 1})

    fz = make_client(handler)
    monkeypatch.setattr(fz, "_retry_auth", lambda: True)
    assert fz.get("/x").status_code == 200
    assert len(calls) == 2


def test_401_revoked_exits_2(make_client, monkeypatch, capsys):
    def handler(req):
        return httpx.Response(
            401,
            json={"detail": "revoked"},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token", error_description="Token revoked"'},
        )

    fz = make_client(handler)
    retried = []
    monkeypatch.setattr(fz, "_retry_auth", lambda: retried.append(1) or True)
    with pytest.raises(SystemExit) as exc:
        fz.get("/x")
    assert exc.value.code == 2
    assert retried == []  # revoked -> no refresh attempt


def test_network_error_exits_10(make_client):
    def handler(req):
        raise httpx.ConnectError("refused")

    fz = make_client(handler)
    with pytest.raises(SystemExit) as exc:
        fz.get("/x")
    assert exc.value.code == 10


@pytest.mark.parametrize(
    "status,expected_exit",
    [(401, 2), (403, 3), (404, 4), (409, 5), (400, 1), (500, 1)],
)
def test_error_exit_codes(make_client, status, expected_exit):
    def handler(req):
        return httpx.Response(status, json={"detail": "nope"})

    fz = make_client(handler)
    with pytest.raises(SystemExit) as exc:
        fz.get("/x")
    assert exc.value.code == expected_exit


def test_422_validation_list_rendered(make_client, capsys):
    def handler(req):
        return httpx.Response(
            422, json={"detail": [{"loc": ["body", "name"], "msg": "field required"}]}
        )

    fz = make_client(handler)
    with pytest.raises(SystemExit):
        fz.get("/x")
    err = capsys.readouterr().err
    assert "body -> name: field required" in err


def test_multipart_files_forwarded(make_client):
    seen = {}

    def handler(req):
        seen["content"] = req.content
        return httpx.Response(201, json={})

    fz = make_client(handler)
    fz.post("/upload", files={"file": ("a.pdf", b"bytes", "application/pdf")})
    assert b"a.pdf" in seen["content"]
