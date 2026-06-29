"""`fz extractions` drives the v2 eager atlas_live API.

The v1 `runs create --pipeline atlas_live` is attach-driven and never dispatches
headlessly; these commands hit `/api/v2/...` which dispatches eagerly. Pin the
payload shape (exactly-one-schema, camelCase aliases) and the POST path.
"""
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from fz_cli.main import cli


def _run(args, env=None, result_json=None):
    captured = {}

    def fake_post(self, path, json=None, **kw):
        captured["post_path"] = path
        captured["json"] = json
        resp = MagicMock()
        resp.json.return_value = {"id": "ext_1", "status": "pending"}
        return resp

    runner = CliRunner()
    with patch("fz_cli.client.FZClient.post", fake_post):
        result = runner.invoke(cli, args, env=env or {})
    return result, captured


def test_extractions_create_with_schema_version():
    result, cap = _run(
        ["-o", "json", "extractions", "create", "-p", "proj_1",
         "--schema-version", "sv_123", "--external-id", "ext-abc"]
    )
    assert result.exit_code == 0, result.output
    assert cap["post_path"] == "/api/v2/projects/proj_1/extractions"
    assert cap["json"]["schemaVersionId"] == "sv_123"
    assert cap["json"]["externalId"] == "ext-abc"
    assert "schema" not in cap["json"]


def test_extractions_create_with_inline_schema():
    result, cap = _run(
        ["-o", "json", "extractions", "create", "-p", "proj_1",
         "--schema", '{"type":"object","properties":{}}']
    )
    assert result.exit_code == 0, result.output
    assert cap["json"]["schema"] == {"type": "object", "properties": {}}
    assert "schemaVersionId" not in cap["json"]


def test_extractions_create_rejects_both_schema_forms():
    result, _ = _run(
        ["extractions", "create", "-p", "proj_1",
         "--schema-version", "sv_1", "--schema", "{}"]
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()


def test_extractions_create_rejects_no_schema():
    result, _ = _run(["extractions", "create", "-p", "proj_1"])
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()


def test_extractions_create_rejects_both_inline_schema_forms(tmp_path):
    f = tmp_path / "s.json"
    f.write_text('{"type":"object","properties":{}}')
    result, _ = _run(
        ["extractions", "create", "-p", "proj_1", "--schema", "{}", "--schema-file", str(f)]
    )
    assert result.exit_code != 0
    assert "exactly one" in result.output.lower()
