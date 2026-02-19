"""Project commands: list, create, get, update, delete."""

from __future__ import annotations

import sys

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output

# Columns for table/csv display of project listings
PROJECT_LIST_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("documentCount", "DOCS"),
    ("schemaCount", "SCHEMAS"),
    ("runCount", "RUNS"),
    ("createdAt", "CREATED"),
]


def resolve_project_id(ctx: click.Context, explicit: str | None = None) -> str:
    """Resolve project ID from explicit argument, context, or error.

    Priority: explicit argument > ctx.obj["project_id"] > error.
    """
    if explicit:
        return explicit

    project_id = ctx.obj.get("project_id")
    if project_id:
        return project_id

    click.echo(
        "Error: No project specified. Pass -p/--project or set "
        "FZ_PROJECT_ID / defaults.project in config.",
        err=True,
    )
    sys.exit(EXIT_GENERAL_ERROR)


@click.group("projects")
def projects_group():
    """Manage projects."""
    pass


@projects_group.command("list")
@click.pass_context
def projects_list(ctx):
    """List all projects."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = client.get("/api/projects")
    data = resp.json()

    format_output(data, columns=PROJECT_LIST_COLUMNS, fmt=fmt, quiet=quiet)


@projects_group.command("create")
@click.argument("name")
@click.option("--description", "-d", default=None, help="Project description.")
@click.pass_context
def projects_create(ctx, name: str, description: str | None):
    """Create a new project."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    payload: dict = {"name": name}
    if description is not None:
        payload["description"] = description

    resp = client.post("/api/projects", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Project created: {data.get('id')}", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


@projects_group.command("get")
@click.argument("project_id", required=False, default=None)
@click.pass_context
def projects_get(ctx, project_id: str | None):
    """Show details for a project."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    pid = resolve_project_id(ctx, project_id)
    resp = client.get(f"/api/projects/{pid}")
    data = resp.json()

    format_output(data, fmt=fmt, quiet=quiet)


@projects_group.command("update")
@click.argument("project_id", required=False, default=None)
@click.option("--name", "-n", default=None, help="New project name.")
@click.option("--description", "-d", default=None, help="New project description.")
@click.pass_context
def projects_update(ctx, project_id: str | None, name: str | None, description: str | None):
    """Update a project's name or description."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    pid = resolve_project_id(ctx, project_id)

    if name is None and description is None:
        click.echo("Error: Provide at least --name or --description to update.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    payload: dict = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    resp = client.put(f"/api/projects/{pid}", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Project updated: {pid}", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


@projects_group.command("delete")
@click.argument("project_id", required=False, default=None)
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def projects_delete(ctx, project_id: str | None, confirm: bool):
    """Delete a project."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    pid = resolve_project_id(ctx, project_id)

    if not confirm:
        click.confirm(f"Delete project {pid}? This cannot be undone", abort=True)

    client.delete(f"/api/projects/{pid}")

    if not quiet:
        click.echo(f"Project deleted: {pid}", err=True)
