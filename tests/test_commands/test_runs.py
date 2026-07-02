"""Tests for `fz runs` (v1)."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
RUN = "55555555-5555-5555-5555-555555555555"
RUN_BODY = {"id": RUN, "status": "running", "schemaName": "Invoice", "createdAt": "2026-07-01"}


def test_create_payload_field_mapping(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/runs", 201, RUN_BODY)
    result = invoke([
        "-p", PROJ, "runs", "create",
        "--schema", "sd-1",
        "--schema-version", "sv-1",
        "--prompt", "pd-1",
        "--prompt-version", "pv-1",
        "--webhook", "wh-1",
        "--external-id", "ext-1",
        "--params", '{"k": 1}',
    ])
    assert result.exit_code == 0, result.output
    body = api.last.json
    assert body["schemaDefinitionId"] == "sd-1"
    assert body["schemaVersionId"] == "sv-1"
    assert body["promptDefinitionId"] == "pd-1"
    assert body["promptVersionId"] == "pv-1"
    assert body["webhookConfigId"] == "wh-1"
    assert body["externalRunId"] == "ext-1"
    assert body["inputParameters"] == {"k": 1}


def test_list_filters_use_camelcase(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/runs", 200,
            {"items": [RUN_BODY], "total": 1, "offset": 0, "limit": 20})
    result = invoke(["-p", PROJ, "runs", "list", "--status", "running", "--schema", "sd-1"])
    assert result.exit_code == 0, result.output
    params = api.last.params
    assert params.get("schemaId") == "sd-1"
    assert params.get("status") == "running"


def test_get(invoke, api):
    api.add("GET", f"/api/runs/{RUN}", 200, RUN_BODY)
    result = invoke(["runs", "get", RUN])
    assert result.exit_code == 0
    assert RUN in result.output


def test_cancel(invoke, api):
    api.add("POST", f"/api/runs/{RUN}/cancel", 200, {**RUN_BODY, "status": "cancelled"})
    result = invoke(["runs", "cancel", RUN])
    assert result.exit_code == 0


def test_cancel_terminal_is_conflict(invoke, api):
    api.add("POST", f"/api/runs/{RUN}/cancel", 409, {"detail": "Run already completed"})
    result = invoke(["runs", "cancel", RUN])
    assert result.exit_code == 5


def test_results_list_and_single(invoke, api):
    api.add("GET", f"/api/runs/{RUN}/results", 200,
            {"items": [{"id": "res-1", "data": {"total": 9}}], "total": 1, "offset": 0, "limit": 50})
    result = invoke(["-o", "json", "runs", "results", RUN])
    assert result.exit_code == 0
    assert "res-1" in result.output

    api.add("GET", f"/api/runs/{RUN}/results/res-1", 200, {"id": "res-1", "data": {"total": 9}})
    result = invoke(["-o", "json", "runs", "results", RUN, "--result", "res-1"])
    assert result.exit_code == 0
    assert api.last.path.endswith("/results/res-1")


def test_documents(invoke, api):
    api.add("GET", f"/api/runs/{RUN}/documents", 200,
            [{"fileName": "spec.pdf", "documentStatus": "ready"}])
    result = invoke(["runs", "documents", RUN])
    assert result.exit_code == 0


def test_events(invoke, api):
    api.add("GET", f"/api/runs/{RUN}/status-events", 200,
            {"items": [{"status": "running", "message": "started", "createdAt": "2026-07-01"}],
             "total": 1, "offset": 0, "limit": 50})
    result = invoke(["runs", "events", RUN])
    assert result.exit_code == 0
    assert "running" in result.output
