"""Tests for `fz schemas` including describe/infer."""

from __future__ import annotations

import json

PROJ = "22222222-2222-2222-2222-222222222222"
SCHEMA = "77777777-7777-7777-7777-777777777777"
SCHEMA_BODY = {"id": SCHEMA, "name": "Invoice", "versionCount": 1}

VALID_SCHEMA = {
    "type": "object",
    "properties": {"total": {"type": "number", "description": "Total value"}},
}


def test_create_from_inline(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/schemas", 201, SCHEMA_BODY)
    result = invoke([
        "-p", PROJ, "schemas", "create", "Invoice",
        "--schema", json.dumps(VALID_SCHEMA),
        "--message", "v1",
    ])
    assert result.exit_code == 0, result.output
    body = api.last.json
    assert body["name"] == "Invoice"
    assert body["jsonSchema"] == VALID_SCHEMA
    assert body["changeDescription"] == "v1"


def test_create_from_file(invoke, api, tmp_path):
    f = tmp_path / "schema.json"
    f.write_text(json.dumps(VALID_SCHEMA))
    api.add("POST", f"/api/projects/{PROJ}/schemas", 201, SCHEMA_BODY)
    result = invoke(["-p", PROJ, "schemas", "create", "Invoice", "--file", str(f)])
    assert result.exit_code == 0, result.output
    assert api.last.json["jsonSchema"] == VALID_SCHEMA


def test_crud(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/schemas", 200, [SCHEMA_BODY])
    assert invoke(["-p", PROJ, "schemas", "list"]).exit_code == 0

    api.add("GET", f"/api/schemas/{SCHEMA}", 200, SCHEMA_BODY)
    assert invoke(["schemas", "get", SCHEMA]).exit_code == 0

    api.add("PUT", f"/api/schemas/{SCHEMA}", 200, SCHEMA_BODY)
    r = invoke(["schemas", "update", SCHEMA, "--description", "d"])
    assert r.exit_code == 0
    assert api.last.json == {"description": "d"}

    api.add("DELETE", f"/api/schemas/{SCHEMA}", 204)
    assert invoke(["schemas", "delete", SCHEMA, "--confirm"]).exit_code == 0


def test_versions(invoke, api):
    api.add("POST", f"/api/schemas/{SCHEMA}/versions", 201, {"id": "sv-2", "versionNumber": 2})
    r = invoke(["schemas", "versions", "create", SCHEMA, "--schema", json.dumps(VALID_SCHEMA)])
    assert r.exit_code == 0, r.output
    assert api.last.json["jsonSchema"] == VALID_SCHEMA

    api.add("GET", f"/api/schemas/{SCHEMA}/versions", 200, [{"id": "sv-1", "versionNumber": 1}])
    assert invoke(["schemas", "versions", "list", SCHEMA]).exit_code == 0

    api.add("GET", f"/api/schemas/{SCHEMA}/versions/2", 200,
            {"id": "sv-2", "versionNumber": 2, "jsonSchema": VALID_SCHEMA})
    assert invoke(["schemas", "versions", "get", SCHEMA, "--version", "2"]).exit_code == 0


def test_versions_diff(invoke, api):
    v1 = {"jsonSchema": {"type": "object", "properties": {"a": {"type": "string", "description": "x"}}}}
    v2 = {"jsonSchema": {"type": "object", "properties": {"a": {"type": "number", "description": "x"}}}}
    api.add("GET", f"/api/schemas/{SCHEMA}/versions/1", 200, v1)
    api.add("GET", f"/api/schemas/{SCHEMA}/versions/2", 200, v2)
    result = invoke(["schemas", "versions", "diff", SCHEMA, "--from", "1", "--to", "2"])
    assert result.exit_code == 0, result.output
    assert "difference" in result.output.lower()


def test_describe(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/schemas/describe", 200,
            {"schema": VALID_SCHEMA, "suggestedName": "Invoice Fields"})
    result = invoke(["-p", PROJ, "-o", "json", "schemas", "describe", "--text", "invoice totals"])
    assert result.exit_code == 0, result.output
    assert api.last.json == {"newInstruction": "invoice totals"}


def test_infer(invoke, api):
    DOC = "66666666-6666-6666-6666-666666666666"
    api.add("POST", f"/api/documents/{DOC}/infer-schema", 200,
            {"schema": {"id": SCHEMA, "name": "Inferred"}})
    result = invoke(["schemas", "infer", "--document", DOC, "--sheet", "Sheet1"])
    assert result.exit_code == 0, result.output
    assert api.last.json == {"sheetName": "Sheet1"}


def test_delete_conflict(invoke, api):
    api.add("DELETE", f"/api/schemas/{SCHEMA}", 409, {"detail": "active runs"})
    result = invoke(["schemas", "delete", SCHEMA, "--confirm"])
    assert result.exit_code == 5
