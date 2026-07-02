"""`fz init` — one command from authenticated to ready-to-extract.

Creates (or reuses) a workspace, creates a project, and writes the project id
to .fluidzero.toml in the current directory so every subsequent fz command
works without -p. Kills the workspace-id -> project-id copy/paste relay that
otherwise sits between `fz auth login` and doing real work.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import click

from ..constants import EXIT_GENERAL_ERROR, LOCAL_CONFIG_FILE


def _write_local_config(project_id: str) -> Path:
    """Write/update the `project` key in .fluidzero.toml, preserving the rest."""
    path = Path.cwd() / LOCAL_CONFIG_FILE
    line = f'project = "{project_id}"'
    if path.is_file():
        text = path.read_text()
        if re.search(r"^project\s*=", text, flags=re.MULTILINE):
            text = re.sub(r'^project\s*=\s*"[^"]*"', line, text, flags=re.MULTILINE)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
        path.write_text(text)
    else:
        path.write_text(f"# fluidzero project config (created by `fz init`)\n{line}\n")
    return path


def _items(data) -> list:
    return data.get("items", []) if isinstance(data, dict) else data


@click.command("init")
@click.argument("name", required=False, default=None)
@click.option("--workspace", "-w", "workspace_id", default=None,
              help="Workspace ID to create the project in (default: your first workspace, created if none exists).")
@click.option("--description", "-d", default=None, help="Project description.")
@click.pass_context
def init_cmd(ctx, name: str | None, workspace_id: str | None, description: str | None):
    """Set up a project here: workspace + project + local config, in one command.

    NAME defaults to the current directory name. After this, run fz commands
    in this directory without -p — the project is remembered in .fluidzero.toml.
    """
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    project_name = name or Path.cwd().name

    # 1) Resolve a workspace: explicit flag > first existing > create one.
    if workspace_id is None:
        workspaces = _items(fz.get("/api/workspaces").json())
        if workspaces:
            workspace_id = workspaces[0]["id"]
            if not quiet:
                click.echo(
                    f"Using workspace: {workspaces[0].get('name', workspace_id)}",
                    err=True,
                )
        else:
            ws = fz.post("/api/workspaces", json={"name": project_name}).json()
            workspace_id = ws["id"]
            if not quiet:
                click.echo(f"Created workspace: {ws.get('name')} ({workspace_id})", err=True)

    # 2) Create the project inside it.
    payload: dict = {"name": project_name, "workspaceId": workspace_id}
    if description:
        payload["description"] = description
    project = fz.post("/api/projects", json=payload).json()
    project_id = project.get("id")
    if not project_id:
        click.echo("Error: project creation returned no id.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    # 3) Remember it locally so -p is never needed in this directory.
    cfg_path = _write_local_config(project_id)

    if not quiet:
        click.echo(f"Created project: {project_name} ({project_id})", err=True)
        click.echo(f"Saved as default project in {cfg_path.name}", err=True)
        click.echo("", err=True)
        click.echo("You're set. Try:", err=True)
        click.echo('  fz extract your.pdf --describe "the fields you want"', err=True)
    # Machine-friendly: the new project id on stdout.
    click.echo(project_id)
