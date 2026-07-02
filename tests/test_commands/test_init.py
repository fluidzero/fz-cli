"""`fz init` — workspace + project + .fluidzero.toml in one command."""

from __future__ import annotations

WS = "44444444-4444-4444-4444-444444444444"
PROJ = "22222222-2222-2222-2222-222222222222"


def test_init_reuses_existing_workspace_and_writes_config(invoke, api, runner):
    api.add("GET", "/api/workspaces", 200,
            {"items": [{"id": WS, "name": "Engineering"}], "total": 1, "offset": 0, "limit": 50})
    api.add("POST", "/api/projects", 201, {"id": PROJ, "name": "my-docs"})

    with runner.isolated_filesystem():
        result = invoke(["init", "my-docs"])
        assert result.exit_code == 0, result.output
        # Project created in the existing workspace, camelCase key.
        assert api.last.json == {"name": "my-docs", "workspaceId": WS}
        # Local config now pins the project.
        content = open(".fluidzero.toml").read()
        assert f'project = "{PROJ}"' in content
        # Machine-friendly stdout: the project id.
        assert PROJ in result.output


def test_init_creates_workspace_when_none_exist(invoke, api, runner):
    api.add("GET", "/api/workspaces", 200, {"items": [], "total": 0, "offset": 0, "limit": 50})
    api.add("POST", "/api/workspaces", 201, {"id": WS, "name": "fresh"})
    api.add("POST", "/api/projects", 201, {"id": PROJ, "name": "fresh"})

    with runner.isolated_filesystem():
        result = invoke(["init", "fresh"])
        assert result.exit_code == 0, result.output
        methods_paths = [(r.method, r.path) for r in api.requests]
        assert ("POST", "/api/workspaces") in methods_paths
        assert ("POST", "/api/projects") in methods_paths


def test_init_defaults_name_to_directory(invoke, api, runner):
    import os
    api.add("GET", "/api/workspaces", 200,
            {"items": [{"id": WS, "name": "Eng"}], "total": 1, "offset": 0, "limit": 50})
    api.add("POST", "/api/projects", 201, {"id": PROJ, "name": "x"})

    with runner.isolated_filesystem():
        os.makedirs("contracts-q3")
        os.chdir("contracts-q3")
        result = invoke(["init"])
        assert result.exit_code == 0, result.output
        assert api.last.json["name"] == "contracts-q3"


def test_init_preserves_existing_local_config(invoke, api, runner):
    api.add("GET", "/api/workspaces", 200,
            {"items": [{"id": WS, "name": "Eng"}], "total": 1, "offset": 0, "limit": 50})
    api.add("POST", "/api/projects", 201, {"id": PROJ, "name": "x"})

    with runner.isolated_filesystem():
        with open(".fluidzero.toml", "w") as fh:
            fh.write('project = "old-project-id"\n\n[upload]\nconcurrency = 8\n')
        result = invoke(["init", "x"])
        assert result.exit_code == 0, result.output
        content = open(".fluidzero.toml").read()
        assert f'project = "{PROJ}"' in content
        assert "old-project-id" not in content
        assert "concurrency = 8" in content  # unrelated settings preserved


def test_init_explicit_workspace_skips_lookup(invoke, api, runner):
    api.add("POST", "/api/projects", 201, {"id": PROJ, "name": "x"})
    with runner.isolated_filesystem():
        result = invoke(["init", "x", "-w", WS])
        assert result.exit_code == 0, result.output
        assert all(r.path != "/api/workspaces" for r in api.requests)
        assert api.last.json["workspaceId"] == WS
