"""`fz projects create` must send the workspaceId the API now requires.

Regression: staging's POST /api/projects rejects a body without workspaceId
(422 "workspace_id is required"). The CLI previously sent only {name,
description}, so `fz projects create` was unusable. It must accept the workspace
via --workspace/-w or the FZ_WORKSPACE_ID env var and include it (camelCase) in
the payload.
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from fz_cli.main import cli


def _run(args, env=None):
    captured = {}

    def fake_post(self, path, json=None, **kw):
        captured["path"] = path
        captured["json"] = json
        resp = MagicMock()
        resp.json.return_value = {"id": "proj_1", "name": "x"}
        return resp

    runner = CliRunner()
    with patch("fz_cli.client.FZClient.post", fake_post):
        result = runner.invoke(cli, args, env=env or {})
    return result, captured


def test_projects_create_sends_workspace_id_from_flag():
    result, captured = _run(
        ["-o", "json", "projects", "create", "My Project", "--workspace", "ws-123"]
    )
    assert result.exit_code == 0, result.output
    assert captured["json"]["name"] == "My Project"
    assert captured["json"]["workspaceId"] == "ws-123"


def test_projects_create_sends_workspace_id_from_env():
    result, captured = _run(
        ["projects", "create", "My Project"],
        env={"FZ_WORKSPACE_ID": "ws-env"},
    )
    assert result.exit_code == 0, result.output
    assert captured["json"]["workspaceId"] == "ws-env"
