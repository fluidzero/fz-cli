"""Tests for `fz search`."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
RESULTS = {"results": [{"content": "Total is $5", "citations": []}]}


def test_project_scoped_body_is_camelcase(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/search", 200, RESULTS)
    result = invoke(["-p", PROJ, "search", "total"])
    assert result.exit_code == 0, result.output
    # SearchRequest only accepts the camelCase alias.
    assert api.last.json.get("includeCitations") is True
    assert api.last.json["query"] == "total"


def test_global_search(invoke, api):
    api.add("POST", "/api/search", 200, RESULTS)
    result = invoke(["search", "total"])
    assert result.exit_code == 0
    assert api.last.path == "/api/search"


def test_no_citations_flag(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/search", 200, RESULTS)
    invoke(["-p", PROJ, "search", "total", "--no-citations"])
    assert api.last.json.get("includeCitations") is False
