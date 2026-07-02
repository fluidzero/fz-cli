"""`fz extract` — the one-command upload -> schema -> extraction -> result flow."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
EXT = "33333333-3333-3333-3333-333333333333"

RESULT = {
    "extractionId": EXT,
    "status": "completed",
    "result": {"total": "$7,192 million"},
    "fields": [],
    "metadata": {},
}


def _mock_extraction_lifecycle(api):
    api.add("POST", f"/api/v2/projects/{PROJ}/extractions", 202,
            {"extractionId": EXT, "status": "pending"})
    api.add("GET", f"/api/v2/extractions/{EXT}", 200,
            {"extractionId": EXT, "status": "completed"})
    api.add("GET", f"/api/v2/extractions/{EXT}/result", 200, RESULT)


def test_extract_with_describe_generates_schema(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/schemas/describe", 200,
            {"schema": {"type": "object", "properties": {
                "total": {"type": "string", "description": "Total value"}}},
             "suggestedName": "Totals"})
    _mock_extraction_lifecycle(api)

    result = invoke(["-o", "json", "-p", PROJ, "extract",
                     "--describe", "the total value"])
    assert result.exit_code == 0, result.output
    describe_req = next(r for r in api.requests if r.path.endswith("/schemas/describe"))
    assert describe_req.json == {"newInstruction": "the total value"}
    create_req = next(r for r in api.requests if r.path.endswith("/extractions"))
    assert create_req.json["schema"]["properties"]["total"]["type"] == "string"
    assert "$7,192 million" in result.output


def test_extract_with_schema_definition(invoke, api):
    api.add("GET", "/api/schemas/sd_1", 200, {"id": "sd_1", "latestVersionNumber": 2})
    api.add("GET", "/api/schemas/sd_1/versions/2", 200, {"id": "sv_2"})
    _mock_extraction_lifecycle(api)

    result = invoke(["-p", PROJ, "extract", "--schema", "sd_1"])
    assert result.exit_code == 0, result.output
    create_req = next(r for r in api.requests if r.path.endswith("/extractions"))
    assert create_req.json == {"schemaVersionId": "sv_2"}


def test_extract_uploads_files_first(invoke, api, tmp_path, monkeypatch):
    uploaded = {}

    def fake_upload(fz, pid, paths, **kw):
        uploaded["pid"] = pid
        uploaded["names"] = [p.name for p in paths]
        uploaded["wait"] = kw.get("wait")
        return [{"id": "doc-1", "status": "ready"}]

    monkeypatch.setattr("fz_cli.commands.extract.upload_files", fake_upload)
    _mock_extraction_lifecycle(api)

    f = tmp_path / "spec.pdf"
    f.write_bytes(b"%PDF")
    result = invoke(["-p", PROJ, "extract", str(f),
                     "--schema-json", '{"type":"object","properties":{}}'])
    assert result.exit_code == 0, result.output
    assert uploaded == {"pid": PROJ, "names": ["spec.pdf"], "wait": True}


def test_extract_requires_exactly_one_schema_source(invoke, api):
    result = invoke(["-p", PROJ, "extract"])
    assert result.exit_code == 1
    assert "exactly one" in result.output

    result = invoke(["-p", PROJ, "extract", "--describe", "x", "--schema", "sd_1"])
    assert result.exit_code == 1
    assert "exactly one" in result.output
    assert api.requests == []


def test_extract_external_id_forwarded(invoke, api):
    _mock_extraction_lifecycle(api)
    result = invoke(["-p", PROJ, "extract",
                     "--schema-json", '{"type":"object","properties":{}}',
                     "--external-id", "job-7"])
    assert result.exit_code == 0, result.output
    create_req = next(r for r in api.requests if r.path.endswith("/extractions"))
    assert create_req.json["externalId"] == "job-7"


def test_extract_failed_extraction_exits_6(invoke, api):
    api.add("POST", f"/api/v2/projects/{PROJ}/extractions", 202,
            {"extractionId": EXT, "status": "pending"})
    api.add("GET", f"/api/v2/extractions/{EXT}", 200,
            {"extractionId": EXT, "status": "failed", "errorMessage": "boom"})
    result = invoke(["-p", PROJ, "extract",
                     "--schema-json", '{"type":"object","properties":{}}'])
    assert result.exit_code == 6
    assert "boom" in result.output


def test_extract_warns_on_empty_completed_result(invoke, api):
    api.add("POST", f"/api/v2/projects/{PROJ}/extractions", 202,
            {"extractionId": EXT, "status": "pending"})
    api.add("GET", f"/api/v2/extractions/{EXT}", 200,
            {"extractionId": EXT, "status": "completed"})
    api.add("GET", f"/api/v2/extractions/{EXT}/result", 200, {
        "extractionId": EXT, "status": "completed",
        "result": {"total": None, "name": None},
        "fields": [], "metadata": {"fields_extracted": 0},
    })
    result = invoke(["-p", PROJ, "extract",
                     "--schema-json", '{"type":"object","properties":{}}'])
    assert result.exit_code == 0
    assert "EMPTY" in result.output
