"""`fz mcp setup` — one command from logged-in to MCP-configured agent."""

from __future__ import annotations

import json


def test_mcp_setup_creates_key_and_prints_configs(invoke, api):
    api.add("POST", "/api/api-keys", 201, {
        "key": {"id": "k1", "name": "MCP - host"},
        "clientId": "client_ABC",
        "clientSecret": "s3cret-once",
    })
    result = invoke(["mcp", "setup", "--name", "MCP - host"])
    assert result.exit_code == 0, result.output

    # Key minted with wildcard scope under the given name.
    assert api.last.json == {"name": "MCP - host", "scopes": ["*"]}

    # Claude Code one-liner with real credentials baked in.
    assert "claude mcp add fluidzero" in result.output
    assert "FZ_CLIENT_ID=client_ABC" in result.output
    assert "FZ_CLIENT_SECRET=s3cret-once" in result.output
    assert "-- fz-mcp" in result.output

    # mcpServers JSON block is valid JSON with the same credentials.
    start = result.output.index('{\n  "mcpServers"')
    depth = 0
    for i, ch in enumerate(result.output[start:], start):
        depth += ch == "{"
        depth -= ch == "}"
        if depth == 0:
            block = json.loads(result.output[start:i + 1])
            break
    server = block["mcpServers"]["fluidzero"]
    assert server["command"] == "fz-mcp"
    assert server["env"]["FZ_CLIENT_ID"] == "client_ABC"
    assert server["env"]["FZ_CLIENT_SECRET"] == "s3cret-once"


def test_mcp_setup_client_filter(invoke, api):
    api.add("POST", "/api/api-keys", 201,
            {"clientId": "client_X", "clientSecret": "s"})
    result = invoke(["mcp", "setup", "--client", "claude-code"])
    assert result.exit_code == 0, result.output
    assert "claude mcp add" in result.output
    assert "mcpServers" not in result.output


def test_mcp_setup_missing_credentials_errors(invoke, api):
    api.add("POST", "/api/api-keys", 201, {"key": {"id": "k1"}})
    result = invoke(["mcp", "setup"])
    assert result.exit_code != 0
    assert "did not return credentials" in result.output
