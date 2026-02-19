"""Prompt management commands: create, list, get, update, delete, and version management."""

from __future__ import annotations

import json
import sys
from typing import Any

import click

from ..output import format_output


def resolve_project_id(ctx: click.Context, project_flag: str | None = None) -> str:
    pid = project_flag or ctx.obj.get("project_id")
    if not pid:
        raise click.UsageError("Project ID required. Use -p/--project or set FZ_PROJECT_ID.")
    return pid


def _load_prompt_text(file: str | None, text: str | None) -> str:
    """Load prompt text from --file or --text, returning the string."""
    if file and text:
        raise click.UsageError("Provide either --file or --text, not both.")
    if file:
        try:
            with open(file) as f:
                return f.read()
        except FileNotFoundError:
            raise click.UsageError(f"File not found: {file}")
    if text:
        return text
    raise click.UsageError("Provide prompt text via --file or --text.")


PROMPT_LIST_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("versionCount", "VERSIONS"),
    ("runCount", "RUNS"),
    ("latestVersionNumber", "LATEST"),
    ("createdAt", "CREATED"),
]

VERSION_LIST_COLUMNS = [
    ("versionNumber", "VERSION"),
    ("changeDescription", "CHANGE DESCRIPTION"),
    ("createdBy", "CREATED BY"),
    ("createdAt", "CREATED"),
]


@click.group("prompts")
@click.pass_context
def prompts_group(ctx: click.Context) -> None:
    """Manage prompts and prompt versions."""
    pass


# ---------------------------------------------------------------------------
# prompts create
# ---------------------------------------------------------------------------
@prompts_group.command("create")
@click.argument("name")
@click.option("-p", "--project", default=None, help="Project ID (or set FZ_PROJECT_ID).")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Path to text file containing the prompt.")
@click.option("--text", "text_str", default=None, help="Inline prompt text.")
@click.option("--description", default=None, help="Prompt description.")
@click.option("--message", "change_description", default=None, help="Change description for the initial version.")
@click.pass_context
def prompts_create(
    ctx: click.Context,
    name: str,
    project: str | None,
    file_path: str | None,
    text_str: str | None,
    description: str | None,
    change_description: str | None,
) -> None:
    """Create a new prompt definition with an initial version."""
    project_id = resolve_project_id(ctx, project)
    prompt_text = _load_prompt_text(file_path, text_str)

    payload: dict[str, Any] = {
        "name": name,
        "promptText": prompt_text,
    }
    if description:
        payload["description"] = description
    if change_description:
        payload["changeDescription"] = change_description

    client = ctx.obj["client"]
    resp = client.post(f"/api/projects/{project_id}/prompts", json=payload)
    data = resp.json()

    format_output(data, columns=PROMPT_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Prompt '{name}' created.", err=True)


# ---------------------------------------------------------------------------
# prompts list
# ---------------------------------------------------------------------------
@prompts_group.command("list")
@click.option("-p", "--project", default=None, help="Project ID (or set FZ_PROJECT_ID).")
@click.pass_context
def prompts_list(ctx: click.Context, project: str | None) -> None:
    """List all prompts in a project."""
    project_id = resolve_project_id(ctx, project)
    client = ctx.obj["client"]
    resp = client.get(f"/api/projects/{project_id}/prompts")
    data = resp.json()

    format_output(data, columns=PROMPT_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# prompts get
# ---------------------------------------------------------------------------
@prompts_group.command("get")
@click.argument("prompt_id")
@click.pass_context
def prompts_get(ctx: click.Context, prompt_id: str) -> None:
    """Get a prompt definition by ID."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/prompts/{prompt_id}")
    data = resp.json()

    format_output(data, columns=PROMPT_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# prompts update
# ---------------------------------------------------------------------------
@prompts_group.command("update")
@click.argument("prompt_id")
@click.option("--name", default=None, help="New prompt name.")
@click.option("--description", default=None, help="New prompt description.")
@click.pass_context
def prompts_update(ctx: click.Context, prompt_id: str, name: str | None, description: str | None) -> None:
    """Update a prompt definition's metadata."""
    if not name and not description:
        raise click.UsageError("Provide at least --name or --description to update.")

    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    client = ctx.obj["client"]
    resp = client.put(f"/api/prompts/{prompt_id}", json=payload)
    data = resp.json()

    format_output(data, columns=PROMPT_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Prompt '{prompt_id}' updated.", err=True)


# ---------------------------------------------------------------------------
# prompts delete
# ---------------------------------------------------------------------------
@prompts_group.command("delete")
@click.argument("prompt_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def prompts_delete(ctx: click.Context, prompt_id: str, confirm: bool) -> None:
    """Delete a prompt definition."""
    if not confirm:
        click.confirm(f"Delete prompt '{prompt_id}'? This cannot be undone", abort=True)

    client = ctx.obj["client"]
    client.delete(f"/api/prompts/{prompt_id}")

    if not ctx.obj["quiet"]:
        click.echo(f"Prompt '{prompt_id}' deleted.", err=True)


# ---------------------------------------------------------------------------
# prompts versions (nested group)
# ---------------------------------------------------------------------------
@prompts_group.group("versions")
@click.pass_context
def versions_group(ctx: click.Context) -> None:
    """Manage prompt versions."""
    pass


# ---------------------------------------------------------------------------
# prompts versions create
# ---------------------------------------------------------------------------
@versions_group.command("create")
@click.argument("prompt_id")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Path to text file containing the prompt.")
@click.option("--text", "text_str", default=None, help="Inline prompt text.")
@click.option("--message", "change_description", default=None, help="Change description for this version.")
@click.pass_context
def versions_create(
    ctx: click.Context,
    prompt_id: str,
    file_path: str | None,
    text_str: str | None,
    change_description: str | None,
) -> None:
    """Create a new version of a prompt."""
    prompt_text = _load_prompt_text(file_path, text_str)

    payload: dict[str, Any] = {
        "promptText": prompt_text,
    }
    if change_description:
        payload["changeDescription"] = change_description

    client = ctx.obj["client"]
    resp = client.post(f"/api/prompts/{prompt_id}/versions", json=payload)
    data = resp.json()

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Version created for prompt '{prompt_id}'.", err=True)


# ---------------------------------------------------------------------------
# prompts versions list
# ---------------------------------------------------------------------------
@versions_group.command("list")
@click.argument("prompt_id")
@click.pass_context
def versions_list(ctx: click.Context, prompt_id: str) -> None:
    """List all versions of a prompt."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/prompts/{prompt_id}/versions")
    data = resp.json()

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# prompts versions get
# ---------------------------------------------------------------------------
@versions_group.command("get")
@click.argument("prompt_id")
@click.option("--version", "version_number", required=True, type=int, help="Version number to retrieve.")
@click.option("--text-only", is_flag=True, default=False, help="Print only the raw prompt text to stdout.")
@click.pass_context
def versions_get(ctx: click.Context, prompt_id: str, version_number: int, text_only: bool) -> None:
    """Get a specific version of a prompt."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/prompts/{prompt_id}/versions/{version_number}")
    data = resp.json()

    if text_only:
        click.echo(data.get("promptText", ""))
        return

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
