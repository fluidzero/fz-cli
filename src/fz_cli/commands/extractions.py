"""Extraction commands (v2 programmatic API): create, get, result, cancel, events.

The v2 API (`/api/v2/...`) is the eager, server-side-dispatched path for the
atlas_live pipeline — unlike `runs create --pipeline atlas_live`, which is
attach-driven (for the browser UI) and never dispatches headlessly. Use these
commands to drive atlas_live extractions to completion from a script/CLI.
"""

from __future__ import annotations

import json as json_mod
import sys
import time

import click

from ..constants import EXIT_GENERAL_ERROR, EXIT_RUN_FAILED, EXIT_TIMEOUT
from ..output import format_output


def _resolve_project_id(ctx: click.Context, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    pid = ctx.obj.get("project_id")
    if pid:
        return pid
    click.echo(
        "Error: No project specified. Pass -p/--project or set "
        "FZ_PROJECT_ID / defaults.project in config.",
        err=True,
    )
    sys.exit(EXIT_GENERAL_ERROR)


def _wait_for_extraction(ctx: click.Context, extraction_id: str, timeout: int | None = None) -> dict:
    """Poll a v2 extraction until terminal or timeout. Returns the final dict."""
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]
    poll_interval = ctx.obj["config"].run_poll_interval
    timeout_secs = timeout or ctx.obj["config"].run_timeout

    start = time.monotonic()
    while True:
        ext = fz.get(f"/api/v2/extractions/{extraction_id}").json()
        status = ext.get("status")
        if not quiet:
            click.echo(
                f"\r  Status: {status}  Progress: {ext.get('progressPercent', '')}%    ",
                nl=False,
                err=True,
            )
        if status in ("completed", "failed", "cancelled"):
            if not quiet:
                click.echo("", err=True)
            break
        if time.monotonic() - start > timeout_secs:
            if not quiet:
                click.echo("", err=True)
            click.echo("Timeout waiting for extraction.", err=True)
            sys.exit(EXIT_TIMEOUT)
        time.sleep(poll_interval)

    if status == "failed":
        click.echo(f"Extraction failed: {ext.get('errorMessage', 'unknown error')}", err=True)
        sys.exit(EXIT_RUN_FAILED)
    return ext


@click.group("extractions")
def extractions_group():
    """Manage v2 extractions (eager atlas_live; scriptable)."""
    pass


def warn_if_result_empty(result: dict) -> None:
    """Warn when a 'completed' v2 extraction produced no actual values.

    A degraded pipeline can complete with error=None while extracting nothing
    (metadata.fields_extracted == 0, all-null result values). Surface that
    loudly instead of letting it read as success.
    """
    meta = result.get("metadata") or {}
    extracted = meta.get("fields_extracted")
    values = result.get("result") or {}
    all_null = isinstance(values, dict) and values and all(
        v in (None, "", [], {}) for v in values.values()
    )
    if extracted == 0 or (extracted is None and all_null):
        click.echo(
            "Warning: extraction completed but every field came back EMPTY. "
            "This usually means the pipeline had a bad run, not that your "
            "documents lack the data. Retry the same command — or check "
            "`fz documents list` shows your documents as 'ready'.",
            err=True,
        )


def resolve_latest_schema_version(fz, schema_id: str) -> str:
    """Resolve a schema DEFINITION id to its latest schema-version id.

    Spares users the schema-id -> versions-list -> version-id relay: pass
    --schema <definition-id> and the newest version is used automatically.
    """
    schema = fz.get(f"/api/schemas/{schema_id}").json()
    latest = schema.get("latestVersionNumber")
    if not latest:
        click.echo(
            f"Error: schema {schema_id} has no versions yet. "
            "Create one with `fz schemas versions create`.",
            err=True,
        )
        sys.exit(EXIT_GENERAL_ERROR)
    version = fz.get(f"/api/schemas/{schema_id}/versions/{latest}").json()
    return version["id"]


@extractions_group.command("create")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--schema", "schema_id", default=None,
              help="Schema ID — the latest version is resolved automatically.")
@click.option("--schema-version", "schema_version_id", default=None,
              help="Pin an exact schema version ID.")
@click.option("--schema-json", "schema_inline", default=None, help="Inline JSON schema string.")
@click.option("--schema-file", "schema_file", type=click.Path(exists=True), default=None,
              help="Path to a JSON file containing the inline schema.")
@click.option("--prompt-version", "prompt_version_id", default=None, help="Prompt version ID.")
@click.option("--webhook", "webhook_id", default=None, help="Webhook config ID.")
@click.option("--external-id", "external_id", default=None, help="External ID for idempotent replay.")
@click.option("--wait", is_flag=True, default=False, help="Wait for completion and show the result.")
@click.option("--timeout", type=int, default=None, help="Timeout in seconds when waiting.")
@click.pass_context
def extractions_create(
    ctx, project_flag, schema_id, schema_version_id, schema_inline, schema_file,
    prompt_version_id, webhook_id, external_id, wait, timeout,
):
    """Create a v2 extraction (one of --schema / --schema-version / --schema-json / --schema-file)."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    # Exactly one schema source across all four inputs.
    n_schema = sum(
        x is not None for x in (schema_id, schema_version_id, schema_inline, schema_file)
    )
    if n_schema != 1:
        click.echo(
            "Error: provide exactly one of --schema, --schema-version, "
            "--schema-json, or --schema-file.",
            err=True,
        )
        sys.exit(EXIT_GENERAL_ERROR)

    inline = None
    if schema_file is not None:
        with open(schema_file) as fh:
            inline = json_mod.load(fh)
    elif schema_inline is not None:
        try:
            inline = json_mod.loads(schema_inline)
        except json_mod.JSONDecodeError as exc:
            click.echo(f"Error: Invalid JSON for --schema-json: {exc}", err=True)
            sys.exit(EXIT_GENERAL_ERROR)

    if schema_id is not None:
        schema_version_id = resolve_latest_schema_version(fz, schema_id)

    payload: dict = {}
    if schema_version_id is not None:
        payload["schemaVersionId"] = schema_version_id
    else:
        payload["schema"] = inline
    if prompt_version_id is not None:
        payload["promptVersionId"] = prompt_version_id
    if webhook_id is not None:
        payload["webhookConfigId"] = webhook_id
    if external_id is not None:
        payload["externalId"] = external_id

    ext = fz.post(f"/api/v2/projects/{pid}/extractions", json=payload).json()
    extraction_id = ext.get("id") or ext.get("extractionId")
    if not quiet:
        click.echo(f"Extraction created: {extraction_id} (status={ext.get('status')})", err=True)

    if wait:
        _wait_for_extraction(ctx, extraction_id, timeout)
        result = fz.get(f"/api/v2/extractions/{extraction_id}/result").json()
        warn_if_result_empty(result)
        format_output(result, fmt=fmt, quiet=quiet)
        return

    format_output(ext, fmt=fmt, quiet=quiet)


@extractions_group.command("get")
@click.argument("extraction_id")
@click.pass_context
def extractions_get(ctx, extraction_id):
    """Show a v2 extraction's status."""
    fz = ctx.obj["client"]
    ext = fz.get(f"/api/v2/extractions/{extraction_id}").json()
    format_output(ext, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


@extractions_group.command("result")
@click.argument("extraction_id")
@click.pass_context
def extractions_result(ctx, extraction_id):
    """Fetch a v2 extraction's result (409 if not yet terminal)."""
    fz = ctx.obj["client"]
    res = fz.get(f"/api/v2/extractions/{extraction_id}/result").json()
    format_output(res, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])


@extractions_group.command("cancel")
@click.argument("extraction_id")
@click.pass_context
def extractions_cancel(ctx, extraction_id):
    """Cancel a pending/running v2 extraction."""
    fz = ctx.obj["client"]
    ext = fz.post(f"/api/v2/extractions/{extraction_id}/cancel").json()
    if not ctx.obj["quiet"]:
        click.echo(f"Extraction cancelled: {extraction_id}", err=True)
    format_output(ext, fmt=ctx.obj["output_format"], quiet=ctx.obj["quiet"])

# NOTE: the v2 GET /api/v2/extractions/{id}/events endpoint is a Server-Sent
# Events stream (text/event-stream), not a JSON list — it needs SSE line
# parsing, not fz.get(...).json(). Use `extractions create --wait` for live
# progress and `extractions get`/`result` for status/output. A streaming
# `events` subcommand is deferred until the client grows SSE support.
