"""Tests for `fz api-keys`."""

from __future__ import annotations

KEY = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def test_create_shows_secret_once(invoke, api):
    api.add("POST", "/api/api-keys", 201,
            {"id": KEY, "name": "CI Key", "clientId": "client_01X",
             "clientSecret": "sekrit-once", "scopes": ["runs:write"]})
    result = invoke(["-o", "json", "api-keys", "create", "CI Key", "--scope", "runs:write"])
    assert result.exit_code == 0, result.output
    assert "sekrit-once" in result.output
    body = api.last.json
    assert body["name"] == "CI Key"
    assert body["scopes"] == ["runs:write"]


def test_list_get(invoke, api):
    api.add("GET", "/api/api-keys", 200, [{"id": KEY, "name": "CI Key", "clientId": "client_01X"}])
    assert invoke(["api-keys", "list"]).exit_code == 0

    api.add("GET", f"/api/api-keys/{KEY}", 200, {"id": KEY, "name": "CI Key"})
    assert invoke(["api-keys", "get", KEY]).exit_code == 0


def test_revoke(invoke, api):
    api.add("DELETE", f"/api/api-keys/{KEY}", 204)
    result = invoke(["api-keys", "revoke", KEY, "--confirm"])
    assert result.exit_code == 0
    assert api.last.method == "DELETE"


def test_revoke_not_creator_forbidden(invoke, api):
    api.add("DELETE", f"/api/api-keys/{KEY}", 403, {"detail": "Only the creator may revoke"})
    result = invoke(["api-keys", "revoke", KEY, "--confirm"])
    assert result.exit_code == 3
