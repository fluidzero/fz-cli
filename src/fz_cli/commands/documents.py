"""Document commands: upload, list, get, delete, download."""

from __future__ import annotations

import glob as glob_mod
import sys
from pathlib import Path

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output
from ..upload import upload_files

# Columns for table/csv display of document listings
DOCUMENT_LIST_COLUMNS = [
    ("id", "ID"),
    ("fileName", "FILE NAME"),
    ("fileType", "TYPE"),
    ("fileSizeBytes", "SIZE (B)"),
    ("status", "STATUS"),
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


@click.group("documents")
def documents_group():
    """Manage documents within a project."""
    pass


@documents_group.command("upload")
@click.argument("files", nargs=-1, required=True)
@click.option("-p", "--project", "project_id", default=None, help="Project ID.")
@click.option("--wait", is_flag=True, help="Wait for processing to complete.")
@click.option("--resume", is_flag=True, help="Resume interrupted uploads.")
@click.pass_context
def documents_upload(ctx, files: tuple[str, ...], project_id: str | None, wait: bool, resume: bool):
    """Upload one or more files to a project.

    FILES can be paths or glob patterns (e.g. docs/*.pdf).
    """
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    pid = resolve_project_id(ctx, project_id)

    # Expand globs and resolve paths
    resolved_paths: list[Path] = []
    for pattern in files:
        p = Path(pattern)
        if p.is_file():
            resolved_paths.append(p.resolve())
        else:
            # Use stdlib glob which handles both relative and absolute patterns
            matches = sorted(Path(m) for m in glob_mod.glob(pattern, recursive=True))
            file_matches = [m for m in matches if m.is_file()]
            if not file_matches:
                click.echo(f"Warning: No files matched '{pattern}'", err=True)
            resolved_paths.extend(file_matches)

    if not resolved_paths:
        click.echo("Error: No files to upload.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    # Remove duplicates while preserving order
    seen: set[Path] = set()
    unique_paths: list[Path] = []
    for fp in resolved_paths:
        if fp not in seen:
            seen.add(fp)
            unique_paths.append(fp)

    documents = upload_files(
        client,
        pid,
        unique_paths,
        wait=wait,
        resume=resume,
        concurrency=ctx.obj["config"].upload_concurrency,
        max_retries=ctx.obj["config"].upload_retry_attempts,
    )

    format_output(documents, columns=DOCUMENT_LIST_COLUMNS, fmt=fmt, quiet=quiet)


@documents_group.command("list")
@click.option("-p", "--project", "project_id", default=None, help="Project ID.")
@click.option("--status", "status_filter", default=None, help="Filter by status (e.g. ready, processing, failed).")
@click.pass_context
def documents_list(ctx, project_id: str | None, status_filter: str | None):
    """List documents in a project."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    pid = resolve_project_id(ctx, project_id)

    params: dict = {}
    if status_filter:
        params["status"] = status_filter

    resp = client.get(f"/api/projects/{pid}/documents", params=params or None)
    data = resp.json()

    format_output(data, columns=DOCUMENT_LIST_COLUMNS, fmt=fmt, quiet=quiet)


@documents_group.command("get")
@click.argument("document_id")
@click.pass_context
def documents_get(ctx, document_id: str):
    """Show details for a document."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = client.get(f"/api/documents/{document_id}")
    data = resp.json()

    format_output(data, fmt=fmt, quiet=quiet)


@documents_group.command("delete")
@click.argument("document_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def documents_delete(ctx, document_id: str, confirm: bool):
    """Delete a document."""
    quiet = ctx.obj["quiet"]
    client = ctx.obj["client"]

    if not confirm:
        click.confirm(f"Delete document {document_id}? This cannot be undone", abort=True)

    client.delete(f"/api/documents/{document_id}")

    if not quiet:
        click.echo(f"Document deleted: {document_id}", err=True)


@documents_group.command("download")
@click.argument("document_id")
@click.option("-o", "--output-dir", default=".", help="Directory to save the downloaded file.")
@click.option("--url-only", is_flag=True, help="Print the presigned URL instead of downloading.")
@click.pass_context
def documents_download(ctx, document_id: str, output_dir: str, url_only: bool):
    """Download a document by ID (via a presigned URL)."""
    client = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    # File name from document metadata; presigned URL from the preview endpoint.
    doc = client.get(f"/api/documents/{document_id}").json()
    file_name = doc.get("fileName") or f"{document_id}.bin"

    url = client.get(f"/api/documents/{document_id}/preview").json().get("url")
    if not url:
        click.echo("Error: API did not return a download URL.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    if url_only:
        click.echo(url)
        return

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / file_name

    raw = client.raw_client()  # shared client — do not close
    with raw.stream("GET", url) as resp:
        if resp.status_code >= 400:
            click.echo(f"Error: download failed with HTTP {resp.status_code}", err=True)
            sys.exit(EXIT_GENERAL_ERROR)
        with open(dest, "wb") as fh:
            for chunk in resp.iter_bytes():
                fh.write(chunk)

    if not quiet:
        click.echo(f"Downloaded: {dest}", err=True)
    # Print the saved path to stdout for scripting.
    click.echo(str(dest))


@documents_group.command("replace")
@click.argument("document_id")
@click.argument("file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.pass_context
def documents_replace(ctx, document_id: str, file: Path):
    """Upload FILE as a new version of an existing document."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    import mimetypes

    mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
    # Bytes (not a handle) so the 401-replay path can resend the body.
    content = file.read_bytes()
    resp = client.post(
        f"/api/documents/{document_id}/versions",
        files={"file": (file.name, content, mime)},
    )
    data = resp.json()

    if not quiet:
        click.echo(f"New version created for document {document_id}", err=True)
    format_output(data, fmt=fmt, quiet=quiet)


@documents_group.command("sheets")
@click.argument("document_id")
@click.pass_context
def documents_sheets(ctx, document_id: str):
    """List worksheet names of an xlsx document."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/documents/{document_id}/sheets")
    format_output(resp.json(), fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


@documents_group.command("status")
@click.option("-p", "--project", "project_id", default=None, help="Project ID.")
@click.option("--document", "document_id", default=None, help="Check a single document.")
@click.pass_context
def documents_status(ctx, project_id: str | None, document_id: str | None):
    """Show processing status for a document or all documents in a project."""
    client = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    if document_id:
        resp = client.get(f"/api/documents/{document_id}/status")
    else:
        pid = resolve_project_id(ctx, project_id)
        resp = client.get(f"/api/projects/{pid}/documents/status")

    format_output(resp.json(), fmt=fmt, quiet=quiet)
