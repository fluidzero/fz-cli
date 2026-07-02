"""Tests for `fz workspaces`."""

from __future__ import annotations

WS = "44444444-4444-4444-4444-444444444444"
WORKSPACE = {"id": WS, "name": "Construction", "projectCount": 2, "createdAt": "2026-07-01"}


def test_list(invoke, api):
    api.add("GET", "/api/workspaces", 200,
            {"items": [WORKSPACE], "total": 1, "offset": 0, "limit": 50})
    result = invoke(["workspaces", "list"])
    assert result.exit_code == 0, result.output
    assert "Construction" in result.output


def test_create(invoke, api):
    api.add("POST", "/api/workspaces", 201, WORKSPACE)
    result = invoke(["workspaces", "create", "Construction", "-d", "AEC"])
    assert result.exit_code == 0, result.output
    assert api.last.json == {"name": "Construction", "description": "AEC"}


def test_get(invoke, api):
    api.add("GET", f"/api/workspaces/{WS}", 200, WORKSPACE)
    result = invoke(["workspaces", "get", WS])
    assert result.exit_code == 0
    assert "Construction" in result.output


def test_update(invoke, api):
    api.add("PUT", f"/api/workspaces/{WS}", 200, WORKSPACE)
    result = invoke(["workspaces", "update", WS, "--name", "Renamed"])
    assert result.exit_code == 0
    assert api.last.json == {"name": "Renamed"}


def test_update_requires_field(invoke, api):
    result = invoke(["workspaces", "update", WS])
    assert result.exit_code == 1
    assert "at least" in result.output
    assert api.requests == []


def test_delete_needs_confirm(invoke, api):
    api.add("DELETE", f"/api/workspaces/{WS}", 204)
    # Without --confirm and answering "n" -> aborted, no request
    result = invoke(["workspaces", "delete", WS], input="n\n")
    assert result.exit_code != 0
    assert api.requests == []
    # With --confirm -> deleted
    result = invoke(["workspaces", "delete", WS, "--confirm"])
    assert result.exit_code == 0
    assert api.last.method == "DELETE"


def test_projects_list_and_create(invoke, api):
    api.add("GET", f"/api/workspaces/{WS}/projects", 200,
            {"items": [{"id": "p1", "name": "Proj A"}], "total": 1, "offset": 0, "limit": 50})
    result = invoke(["workspaces", "projects", "list", WS])
    assert result.exit_code == 0
    assert "Proj A" in result.output

    api.add("POST", f"/api/workspaces/{WS}/projects", 201, {"id": "p2", "name": "Proj B"})
    result = invoke(["workspaces", "projects", "create", WS, "Proj B"])
    assert result.exit_code == 0
    assert api.last.json == {"name": "Proj B"}


def test_runs(invoke, api):
    api.add("GET", f"/api/workspaces/{WS}/runs", 200,
            {"items": [{"id": "r1", "status": "completed", "projectId": "p1"}],
             "total": 1, "offset": 0, "limit": 20})
    result = invoke(["workspaces", "runs", WS, "--status", "completed"])
    assert result.exit_code == 0
    assert "completed" in result.output
    assert api.last.params["status"] == "completed"


def test_forbidden_exit_code(invoke, api):
    api.add("GET", f"/api/workspaces/{WS}", 403, {"detail": "Access denied"})
    result = invoke(["workspaces", "get", WS])
    assert result.exit_code == 3
