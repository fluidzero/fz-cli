"""Schema management commands: create, list, get, update, delete, and version management."""

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


def _load_json_schema(file: str | None, schema_str: str | None) -> dict[str, Any]:
    """Load JSON schema from --file or --schema, returning parsed dict."""
    if file and schema_str:
        raise click.UsageError("Provide either --file or --schema, not both.")
    if file:
        try:
            with open(file) as f:
                return json.load(f)
        except FileNotFoundError:
            raise click.UsageError(f"File not found: {file}")
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"Invalid JSON in {file}: {exc}")
    if schema_str:
        try:
            return json.loads(schema_str)
        except json.JSONDecodeError as exc:
            raise click.UsageError(f"Invalid JSON string: {exc}")
    raise click.UsageError("Provide a JSON schema via --file or --schema.")


SCHEMA_LIST_COLUMNS = [
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


@click.group("schemas")
@click.pass_context
def schemas_group(ctx: click.Context) -> None:
    """Manage schemas and schema versions."""
    pass


# ---------------------------------------------------------------------------
# schemas create
# ---------------------------------------------------------------------------
@schemas_group.command("create")
@click.argument("name")
@click.option("-p", "--project", default=None, help="Project ID (or set FZ_PROJECT_ID).")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Path to JSON file containing the schema.")
@click.option("--schema", "schema_str", default=None, help="Inline JSON string for the schema.")
@click.option("--description", default=None, help="Schema description.")
@click.option("--message", "change_description", default=None, help="Change description for the initial version.")
@click.pass_context
def schemas_create(
    ctx: click.Context,
    name: str,
    project: str | None,
    file_path: str | None,
    schema_str: str | None,
    description: str | None,
    change_description: str | None,
) -> None:
    """Create a new schema definition with an initial version."""
    project_id = resolve_project_id(ctx, project)
    json_schema = _load_json_schema(file_path, schema_str)

    payload: dict[str, Any] = {
        "name": name,
        "jsonSchema": json_schema,
    }
    if description:
        payload["description"] = description
    if change_description:
        payload["changeDescription"] = change_description

    client = ctx.obj["client"]
    resp = client.post(f"/api/projects/{project_id}/schemas", json=payload)
    data = resp.json()

    format_output(data, columns=SCHEMA_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Schema '{name}' created.", err=True)


# ---------------------------------------------------------------------------
# schemas list
# ---------------------------------------------------------------------------
@schemas_group.command("list")
@click.option("-p", "--project", default=None, help="Project ID (or set FZ_PROJECT_ID).")
@click.pass_context
def schemas_list(ctx: click.Context, project: str | None) -> None:
    """List all schemas in a project."""
    project_id = resolve_project_id(ctx, project)
    client = ctx.obj["client"]
    resp = client.get(f"/api/projects/{project_id}/schemas")
    data = resp.json()

    format_output(data, columns=SCHEMA_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# schemas get
# ---------------------------------------------------------------------------
@schemas_group.command("get")
@click.argument("schema_id")
@click.pass_context
def schemas_get(ctx: click.Context, schema_id: str) -> None:
    """Get a schema definition by ID."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/schemas/{schema_id}")
    data = resp.json()

    format_output(data, columns=SCHEMA_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# schemas update
# ---------------------------------------------------------------------------
@schemas_group.command("update")
@click.argument("schema_id")
@click.option("--name", default=None, help="New schema name.")
@click.option("--description", default=None, help="New schema description.")
@click.pass_context
def schemas_update(ctx: click.Context, schema_id: str, name: str | None, description: str | None) -> None:
    """Update a schema definition's metadata."""
    if not name and not description:
        raise click.UsageError("Provide at least --name or --description to update.")

    payload: dict[str, Any] = {}
    if name is not None:
        payload["name"] = name
    if description is not None:
        payload["description"] = description

    client = ctx.obj["client"]
    resp = client.put(f"/api/schemas/{schema_id}", json=payload)
    data = resp.json()

    format_output(data, columns=SCHEMA_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Schema '{schema_id}' updated.", err=True)


# ---------------------------------------------------------------------------
# schemas delete
# ---------------------------------------------------------------------------
@schemas_group.command("delete")
@click.argument("schema_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def schemas_delete(ctx: click.Context, schema_id: str, confirm: bool) -> None:
    """Delete a schema definition."""
    if not confirm:
        click.confirm(f"Delete schema '{schema_id}'? This cannot be undone", abort=True)

    client = ctx.obj["client"]
    client.delete(f"/api/schemas/{schema_id}")

    if not ctx.obj["quiet"]:
        click.echo(f"Schema '{schema_id}' deleted.", err=True)


# ---------------------------------------------------------------------------
# schemas versions (nested group)
# ---------------------------------------------------------------------------
@schemas_group.group("versions")
@click.pass_context
def versions_group(ctx: click.Context) -> None:
    """Manage schema versions."""
    pass


# ---------------------------------------------------------------------------
# schemas versions create
# ---------------------------------------------------------------------------
@versions_group.command("create")
@click.argument("schema_id")
@click.option("--file", "file_path", default=None, type=click.Path(exists=True), help="Path to JSON file containing the schema.")
@click.option("--schema", "schema_str", default=None, help="Inline JSON string for the schema.")
@click.option("--message", "change_description", default=None, help="Change description for this version.")
@click.pass_context
def versions_create(
    ctx: click.Context,
    schema_id: str,
    file_path: str | None,
    schema_str: str | None,
    change_description: str | None,
) -> None:
    """Create a new version of a schema."""
    json_schema = _load_json_schema(file_path, schema_str)

    payload: dict[str, Any] = {
        "jsonSchema": json_schema,
    }
    if change_description:
        payload["changeDescription"] = change_description

    client = ctx.obj["client"]
    resp = client.post(f"/api/schemas/{schema_id}/versions", json=payload)
    data = resp.json()

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])
    if not ctx.obj["quiet"]:
        click.echo(f"Version created for schema '{schema_id}'.", err=True)


# ---------------------------------------------------------------------------
# schemas versions list
# ---------------------------------------------------------------------------
@versions_group.command("list")
@click.argument("schema_id")
@click.pass_context
def versions_list(ctx: click.Context, schema_id: str) -> None:
    """List all versions of a schema."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/schemas/{schema_id}/versions")
    data = resp.json()

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# schemas versions get
# ---------------------------------------------------------------------------
@versions_group.command("get")
@click.argument("schema_id")
@click.option("--version", "version_number", required=True, type=int, help="Version number to retrieve.")
@click.pass_context
def versions_get(ctx: click.Context, schema_id: str, version_number: int) -> None:
    """Get a specific version of a schema."""
    client = ctx.obj["client"]
    resp = client.get(f"/api/schemas/{schema_id}/versions/{version_number}")
    data = resp.json()

    format_output(data, columns=VERSION_LIST_COLUMNS, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


# ---------------------------------------------------------------------------
# schemas versions diff
# ---------------------------------------------------------------------------
def _deep_diff(old: Any, new: Any, path: str = "") -> list[str]:
    """Recursively diff two JSON-like structures, returning human-readable lines."""
    lines: list[str] = []
    prefix = path or "(root)"

    if type(old) != type(new):
        lines.append(f"  changed {prefix}: {_summarize(old)} -> {_summarize(new)}")
        return lines

    if isinstance(old, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key not in old:
                lines.append(f"  + added {child_path}: {_summarize(new[key])}")
            elif key not in new:
                lines.append(f"  - removed {child_path}: {_summarize(old[key])}")
            else:
                lines.extend(_deep_diff(old[key], new[key], child_path))
    elif isinstance(old, list):
        max_len = max(len(old), len(new))
        for i in range(max_len):
            child_path = f"{path}[{i}]"
            if i >= len(old):
                lines.append(f"  + added {child_path}: {_summarize(new[i])}")
            elif i >= len(new):
                lines.append(f"  - removed {child_path}: {_summarize(old[i])}")
            else:
                lines.extend(_deep_diff(old[i], new[i], child_path))
    else:
        if old != new:
            lines.append(f"  changed {prefix}: {_summarize(old)} -> {_summarize(new)}")

    return lines


def _summarize(value: Any) -> str:
    """Short string representation of a value for diff output."""
    s = json.dumps(value, default=str)
    if len(s) > 80:
        return s[:77] + "..."
    return s


@versions_group.command("diff")
@click.argument("schema_id")
@click.option("--from", "from_version", required=True, type=int, help="Base version number.")
@click.option("--to", "to_version", required=True, type=int, help="Target version number.")
@click.pass_context
def versions_diff(ctx: click.Context, schema_id: str, from_version: int, to_version: int) -> None:
    """Compare two schema versions and show differences."""
    client = ctx.obj["client"]

    resp_from = client.get(f"/api/schemas/{schema_id}/versions/{from_version}")
    resp_to = client.get(f"/api/schemas/{schema_id}/versions/{to_version}")

    data_from = resp_from.json()
    data_to = resp_to.json()

    schema_from = data_from.get("jsonSchema", {})
    schema_to = data_to.get("jsonSchema", {})

    # JSON output mode: emit both schemas and the diff as structured data
    if ctx.obj["output_format"] == "json":
        diff_result = {
            "schemaId": schema_id,
            "fromVersion": from_version,
            "toVersion": to_version,
            "fromSchema": schema_from,
            "toSchema": schema_to,
            "differences": _deep_diff(schema_from, schema_to),
        }
        click.echo(json.dumps(diff_result, indent=2, default=str))
        return

    # Human-readable diff output
    diff_lines = _deep_diff(schema_from, schema_to)

    click.echo(f"Schema diff: v{from_version} -> v{to_version}")
    click.echo(f"Schema: {schema_id}")
    click.echo("")

    if not diff_lines:
        click.echo("No differences found.")
    else:
        click.echo(f"{len(diff_lines)} difference(s):")
        click.echo("")
        for line in diff_lines:
            click.echo(line)
