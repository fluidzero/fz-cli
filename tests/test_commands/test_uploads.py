"""Tests for `fz uploads` management group."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
UP = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_list(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/uploads", 200,
            {"items": [{"id": UP, "fileName": "big.pdf", "status": "uploading", "totalParts": 4}],
             "total": 1, "offset": 0, "limit": 50})
    result = invoke(["-p", PROJ, "uploads", "list"])
    assert result.exit_code == 0, result.output
    assert "big.pdf" in result.output


def test_get(invoke, api):
    api.add("GET", f"/api/uploads/{UP}", 200,
            {"id": UP, "fileName": "big.pdf", "status": "uploading", "uploadedParts": [1, 2]})
    result = invoke(["uploads", "get", UP])
    assert result.exit_code == 0


def test_abort(invoke, api):
    api.add("DELETE", f"/api/uploads/{UP}", 204)
    result = invoke(["uploads", "abort", UP, "--confirm"])
    assert result.exit_code == 0
    assert api.last.method == "DELETE"


def test_abort_completed_is_error(invoke, api):
    api.add("DELETE", f"/api/uploads/{UP}", 400, {"detail": "Upload already completed"})
    result = invoke(["uploads", "abort", UP, "--confirm"])
    assert result.exit_code == 1
    assert "completed" in result.output
