"""Tests for `fz prompts`."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
PROMPT = "88888888-8888-8888-8888-888888888888"
PROMPT_BODY = {"id": PROMPT, "name": "Extractor"}


def test_create_with_text(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/prompts", 201, PROMPT_BODY)
    result = invoke(["-p", PROJ, "prompts", "create", "Extractor", "--text", "Extract totals."])
    assert result.exit_code == 0, result.output
    body = api.last.json
    assert body["name"] == "Extractor"
    assert body["promptText"] == "Extract totals."


def test_crud(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/prompts", 200, [PROMPT_BODY])
    assert invoke(["-p", PROJ, "prompts", "list"]).exit_code == 0

    api.add("GET", f"/api/prompts/{PROMPT}", 200, PROMPT_BODY)
    assert invoke(["prompts", "get", PROMPT]).exit_code == 0

    api.add("PUT", f"/api/prompts/{PROMPT}", 200, PROMPT_BODY)
    r = invoke(["prompts", "update", PROMPT, "--name", "Renamed"])
    assert r.exit_code == 0
    assert api.last.json == {"name": "Renamed"}

    api.add("DELETE", f"/api/prompts/{PROMPT}", 204)
    assert invoke(["prompts", "delete", PROMPT, "--confirm"]).exit_code == 0


def test_versions_and_text_only(invoke, api):
    api.add("POST", f"/api/prompts/{PROMPT}/versions", 201, {"id": "pv-2", "versionNumber": 2})
    r = invoke(["prompts", "versions", "create", PROMPT, "--text", "New text"])
    assert r.exit_code == 0, r.output
    assert api.last.json["promptText"] == "New text"

    api.add("GET", f"/api/prompts/{PROMPT}/versions", 200, [{"id": "pv-1", "versionNumber": 1}])
    assert invoke(["prompts", "versions", "list", PROMPT]).exit_code == 0

    api.add("GET", f"/api/prompts/{PROMPT}/versions/1", 200,
            {"id": "pv-1", "versionNumber": 1, "promptText": "The raw text"})
    result = invoke(["prompts", "versions", "get", PROMPT, "--version", "1", "--text-only"])
    assert result.exit_code == 0
    assert result.output.strip() == "The raw text"
