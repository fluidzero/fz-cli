"""Tests for `fz webhooks`."""

from __future__ import annotations

PROJ = "22222222-2222-2222-2222-222222222222"
WH = "99999999-9999-9999-9999-999999999999"
WEBHOOK = {"id": WH, "name": "notify", "url": "https://example.com/hook",
           "eventTypes": ["run.completed"], "isActive": True, "createdAt": "2026-07-01"}


def test_create(invoke, api):
    api.add("POST", f"/api/projects/{PROJ}/webhooks", 201, WEBHOOK)
    result = invoke([
        "-p", PROJ, "webhooks", "create",
        "--name", "notify",
        "--url", "https://example.com/hook",
        "--event", "run.completed",
        "--event", "run.failed",
        "--secret", "s3cret",
    ])
    assert result.exit_code == 0, result.output
    body = api.last.json
    assert body["url"] == "https://example.com/hook"
    # EV aliases event_types as "events" — "eventTypes" is silently dropped.
    assert body["events"] == ["run.completed", "run.failed"]
    assert body["secret"] == "s3cret"


def test_list_get_update_delete_test(invoke, api):
    api.add("GET", f"/api/projects/{PROJ}/webhooks", 200, [WEBHOOK])
    assert invoke(["-p", PROJ, "webhooks", "list"]).exit_code == 0

    api.add("GET", f"/api/webhooks/{WH}", 200, WEBHOOK)
    assert invoke(["webhooks", "get", WH]).exit_code == 0

    api.add("PUT", f"/api/webhooks/{WH}", 200, WEBHOOK)
    r = invoke(["webhooks", "update", WH, "--name", "renamed"])
    assert r.exit_code == 0

    api.add("POST", f"/api/webhooks/{WH}/test", 200, {"success": True, "statusCode": 200})
    assert invoke(["webhooks", "test", WH]).exit_code == 0

    api.add("DELETE", f"/api/webhooks/{WH}", 204)
    assert invoke(["webhooks", "delete", WH, "--confirm"]).exit_code == 0


def test_deliveries_list(invoke, api):
    api.add("GET", f"/api/webhooks/{WH}/deliveries", 200,
            {"items": [{"id": "del-1", "eventType": "run.completed", "success": True}],
             "total": 1, "offset": 0, "limit": 20})
    result = invoke(["webhooks", "deliveries", WH, "--event-type", "run.completed"])
    assert result.exit_code == 0
    assert api.last.params["eventType"] == "run.completed"


def test_deliveries_single(invoke, api):
    api.add("GET", f"/api/webhooks/{WH}/deliveries/del-1", 200,
            {"id": "del-1", "eventType": "run.failed", "requestPayload": {"runId": "r1"}})
    result = invoke(["-o", "json", "webhooks", "deliveries", WH, "--delivery", "del-1"])
    assert result.exit_code == 0
    assert "del-1" in result.output


def test_m2m_sid_error_maps_to_auth_exit(invoke, api):
    api.add("GET", f"/api/webhooks/{WH}", 401,
            {"detail": "Invalid token: missing 'sid' claim"},
            headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    result = invoke(["webhooks", "get", WH])
    assert result.exit_code == 2
    assert "sid" in result.output
