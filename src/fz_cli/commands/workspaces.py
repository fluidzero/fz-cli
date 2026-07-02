"""Workspace commands: list, create, get, update, delete, projects, runs."""

from __future__ import annotations

import sys

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output

WORKSPACE_LIST_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("projectCount", "PROJECTS"),
    ("createdAt", "CREATED"),
]

WORKSPACE_PROJECT_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("documentCount", "DOCS"),
    ("createdAt", "CREATED"),
]

WORKSPACE_RUN_COLUMNS = [
    ("id", "ID"),
    ("projectId", "PROJECT"),
    ("status", "STATUS"),
    ("schemaName", "SCHEMA"),
    ("createdAt", "CREATED"),
]


@click.group("workspaces")
def workspaces_group():
    """Manage workspaces (top-level containers for projects)."""
    pass


@workspaces_group.command("list")
@click.pass_context
def workspaces_list(ctx):
    """List all workspaces."""
    client = ctx.obj["client"]
    resp = client.get("/api/workspaces")
    format_output(
        resp.json(),
        columns=WORKSPACE_LIST_COLUMNS,
        fmt=ctx.obj["output_format"],
        quiet=ctx.obj["quiet"],
    )


@workspaces_group.command("create")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Workspace description.")
@click.pass_context
def workspaces_create(ctx, name: str, description: str | None):
    """Create a new workspace."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description

    resp = client.post("/api/workspaces", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Workspace created: {data.get('id')}", err=True)
    format_output(data, fmt=ctx.obj["output_format"], quiet=quiet)


@workspaces_group.command("get")
@click.argument("workspace_id")
@click.pass_context
def workspaces_get(ctx, workspace_id: str):
    """Show details for a workspace."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/workspaces/{workspace_id}")
    format_output(resp.json(), fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


@workspaces_group.command("update")
@click.argument("workspace_id")
@click.option("--name", "-n", default=None, help="New workspace name.")
@click.option("--description", "-d", default=None, help="New workspace description.")
@click.pass_context
def workspaces_update(ctx, workspace_id: str, name: str | None, description: str | None):
    """Update a workspace's name or description."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    if name is None and description is None:
        click.echo("Error: Provide at least --name or --description to update.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    payload: dict = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    resp = client.put(f"/api/workspaces/{workspace_id}", json=payload)

    if not quiet:
        click.echo(f"Workspace updated: {workspace_id}", err=True)
    format_output(resp.json(), fmt=ctx.obj["output_format"], quiet=quiet)


@workspaces_group.command("delete")
@click.argument("workspace_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def workspaces_delete(ctx, workspace_id: str, confirm: bool):
    """Delete (archive) a workspace."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    if not confirm:
        click.confirm(f"Delete workspace {workspace_id}? This cannot be undone", abort=True)

    client.delete(f"/api/workspaces/{workspace_id}")

    if not quiet:
        click.echo(f"Workspace deleted: {workspace_id}", err=True)


@workspaces_group.group("projects")
def workspaces_projects():
    """Manage projects within a workspace."""
    pass


@workspaces_projects.command("list")
@click.argument("workspace_id")
@click.pass_context
def workspaces_projects_list(ctx, workspace_id: str):
    """List projects in a workspace."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/workspaces/{workspace_id}/projects")
    format_output(
        resp.json(),
        columns=WORKSPACE_PROJECT_COLUMNS,
        fmt=ctx.obj["output_format"],
        quiet=ctx.obj["quiet"],
    )


@workspaces_projects.command("create")
@click.argument("workspace_id")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Project description.")
@click.pass_context
def workspaces_projects_create(ctx, workspace_id: str, name: str, description: str | None):
    """Create a project inside a workspace."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description

    resp = client.post(f"/api/workspaces/{workspace_id}/projects", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Project created: {data.get('id')}", err=True)
    format_output(data, fmt=ctx.obj["output_format"], quiet=quiet)


@workspaces_group.command("runs")
@click.argument("workspace_id")
@click.option("--status", default=None, help="Filter by run status.")
@click.option("--limit", default=20, show_default=True, help="Max results.")
@click.option("--offset", default=0, show_default=True, help="Pagination offset.")
@click.pass_context
def workspaces_runs(ctx, workspace_id: str, status: str | None, limit: int, offset: int):
    """List runs across all projects in a workspace."""
    client = ctx.obj["client"]

    params: dict = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status

    resp = client.get(f"/api/workspaces/{workspace_id}/runs", params=params)
    format_output(
        resp.json(),
        columns=WORKSPACE_RUN_COLUMNS,
        fmt=ctx.obj["output_format"],
        quiet=ctx.obj["quiet"],
    )
