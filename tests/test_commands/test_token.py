"""TokenManager.get_access_token must never hand back a stale/expired token.

Regression: when the access token is expired and refresh fails (e.g. the refresh
token is itself expired/revoked), get_access_token previously fell through to
`return self._access_token`, handing callers a dead JWT that 401s opaquely
downstream. It must return None so the caller can detect "re-auth required".
"""
import time

from fz_cli.auth.token import TokenManager


def _mgr(access="tok", refresh="rt", expires_at=0):
    m = TokenManager("http://api.test")
    m._access_token = access
    m._refresh_token = refresh
    m._expires_at = expires_at
    return m


def test_returns_token_when_not_expired():
    m = _mgr(expires_at=int(time.time()) + 3600)
    assert m.get_access_token() == "tok"


def test_returns_none_when_expired_and_refresh_fails(monkeypatch):
    m = _mgr(expires_at=0)  # already expired
    monkeypatch.setattr(m, "refresh", lambda: False)  # refresh token dead
    assert m.get_access_token() is None


def test_returns_refreshed_token_when_refresh_succeeds(monkeypatch):
    m = _mgr(expires_at=0)

    def fake_refresh():
        m._access_token = "newtok"
        m._expires_at = int(time.time()) + 3600
        return True

    monkeypatch.setattr(m, "refresh", fake_refresh)
    assert m.get_access_token() == "newtok"


def test_returns_none_when_expired_and_no_refresh_token():
    m = _mgr(refresh=None, expires_at=0)
    assert m.get_access_token() is None
