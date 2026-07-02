"""Upload management commands: list, get, abort (resumable multipart uploads)."""

from __future__ import annotations

import click

from ..output import format_output
from .projects import resolve_project_id

UPLOAD_LIST_COLUMNS = [
    ("id", "ID"),
    ("fileName", "FILE NAME"),
    ("status", "STATUS"),
    ("totalParts", "PARTS"),
    ("createdAt", "CREATED"),
]


@click.group("uploads")
def uploads_group():
    """Inspect and manage in-progress multipart uploads."""
    pass


@uploads_group.command("list")
@click.option("-p", "--project", "project_id", default=None, help="Project ID.")
@click.pass_context
def uploads_list(ctx, project_id: str | None):
    """List multipart uploads for a project."""
    client = ctx.obj["client"]
    pid = resolve_project_id(ctx, project_id)
    resp = client.get(f"/api/projects/{pid}/uploads")
    format_output(
        resp.json(),
        columns=UPLOAD_LIST_COLUMNS,
        fmt=ctx.obj["output_format"],
        quiet=ctx.obj["quiet"],
    )


@uploads_group.command("get")
@click.argument("upload_id")
@click.pass_context
def uploads_get(ctx, upload_id: str):
    """Show status of a multipart upload (including uploaded parts)."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/uploads/{upload_id}")
    format_output(resp.json(), fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


@uploads_group.command("abort")
@click.argument("upload_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def uploads_abort(ctx, upload_id: str, confirm: bool):
    """Abort an in-progress multipart upload and clean up its parts."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    if not confirm:
        click.confirm(f"Abort upload {upload_id}?", abort=True)

    client.delete(f"/api/uploads/{upload_id}")

    if not quiet:
        click.echo(f"Upload aborted: {upload_id}", err=True)
