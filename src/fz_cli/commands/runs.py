"""Run commands: create, list, get, watch, cancel, results, documents, events."""

from __future__ import annotations

import json as json_mod
import sys
import time

import click

from ..constants import EXIT_GENERAL_ERROR, EXIT_RUN_FAILED, EXIT_TIMEOUT
from ..output import format_output


# ── Table column definitions ────────────────────────────────────────────────

RUN_LIST_COLUMNS = [
    ("id", "ID"),
    ("status", "STATUS"),
    ("schemaName", "SCHEMA"),
    ("versionNumber", "VERSION"),
    ("resultCount", "RESULTS"),
    ("durationSeconds", "DURATION(s)"),
    ("createdAt", "CREATED"),
]

RESULT_LIST_COLUMNS = [
    ("sequenceNumber", "SEQ"),
    ("documentId", "DOCUMENT"),
    ("qualityScore", "QUALITY"),
    ("data", "DATA"),
]

DOCUMENT_LIST_COLUMNS = [
    ("id", "ID"),
    ("documentId", "DOCUMENT"),
    ("fileName", "FILE"),
    ("status", "STATUS"),
    ("createdAt", "CREATED"),
]

EVENT_LIST_COLUMNS = [
    ("id", "ID"),
    ("status", "STATUS"),
    ("message", "MESSAGE"),
    ("createdAt", "CREATED"),
]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _resolve_project_id(ctx: click.Context, explicit: str | None = None) -> str:
    """Resolve project ID from explicit argument, context, or error."""
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


def _wait_for_run(ctx: click.Context, run_id: str, timeout: int | None = None) -> dict:
    """Poll a run until it reaches a terminal status or times out.

    Returns the final run dict.
    """
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]
    poll_interval = ctx.obj["config"].run_poll_interval
    timeout_secs = timeout or ctx.obj["config"].run_timeout

    start = time.monotonic()
    while True:
        resp = fz.get(f"/api/runs/{run_id}")
        run = resp.json()
        status = run.get("status")

        if not quiet:
            progress = run.get("progressPercent", "")
            msg = run.get("progressMessage", "")
            click.echo(
                f"\r  Status: {status}  Progress: {progress}%  {msg}    ",
                nl=False,
                err=True,
            )

        if status in ("completed", "failed", "cancelled"):
            if not quiet:
                click.echo("", err=True)  # newline after carriage-return updates
            break

        elapsed = time.monotonic() - start
        if elapsed > timeout_secs:
            if not quiet:
                click.echo("", err=True)
            click.echo("Timeout waiting for run.", err=True)
            sys.exit(EXIT_TIMEOUT)

        time.sleep(poll_interval)

    if status == "failed":
        error_msg = run.get("errorMessage", "unknown error")
        click.echo(f"Run failed: {error_msg}", err=True)
        sys.exit(EXIT_RUN_FAILED)

    return run


# ── Click group ─────────────────────────────────────────────────────────────

@click.group("runs")
def runs_group():
    """Manage extraction runs."""
    pass


# ── create ──────────────────────────────────────────────────────────────────

@runs_group.command("create")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--schema", "schema_id", required=True, help="Schema definition ID.")
@click.option("--schema-version", "schema_version_id", default=None, help="Schema version ID.")
@click.option("--prompt", "prompt_id", default=None, help="Prompt definition ID.")
@click.option("--prompt-version", "prompt_version_id", default=None, help="Prompt version ID.")
@click.option("--webhook", "webhook_id", default=None, help="Webhook config ID.")
@click.option("--params", "params_json", default=None, help="Input parameters as JSON string.")
@click.option("--external-id", "external_id", default=None, help="External run ID for tracking.")
@click.option("--pipeline", default=None, help="Pipeline identifier.")
@click.option("--wait", is_flag=True, default=False, help="Wait for run to complete.")
@click.option(
    "--timeout", type=int, default=None,
    help="Timeout in seconds when waiting (default from config).",
)
@click.pass_context
def runs_create(
    ctx,
    project_flag,
    schema_id,
    schema_version_id,
    prompt_id,
    prompt_version_id,
    webhook_id,
    params_json,
    external_id,
    pipeline,
    wait,
    timeout,
):
    """Create a new extraction run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    # Build request body with camelCase aliases
    payload: dict = {"schemaDefinitionId": schema_id}

    if schema_version_id is not None:
        payload["schemaVersionId"] = schema_version_id
    if prompt_id is not None:
        payload["promptDefinitionId"] = prompt_id
    if prompt_version_id is not None:
        payload["promptVersionId"] = prompt_version_id
    if webhook_id is not None:
        payload["webhookConfigId"] = webhook_id
    if external_id is not None:
        payload["externalRunId"] = external_id
    if pipeline is not None:
        payload["pipeline"] = pipeline

    if params_json is not None:
        try:
            payload["inputParameters"] = json_mod.loads(params_json)
        except json_mod.JSONDecodeError as exc:
            click.echo(f"Error: Invalid JSON for --params: {exc}", err=True)
            sys.exit(EXIT_GENERAL_ERROR)

    resp = fz.post(f"/api/projects/{pid}/runs", json=payload)
    run = resp.json()
    run_id = run.get("id")

    if not quiet:
        click.echo(f"Run created: {run_id}", err=True)

    if wait:
        try:
            run = _wait_for_run(ctx, run_id, timeout=timeout)
        except KeyboardInterrupt:
            click.echo(f"\nInterrupted. Run {run_id} continues on server.", err=True)
            return

    format_output(run, fmt=fmt, quiet=quiet)


# ── list ────────────────────────────────────────────────────────────────────

@runs_group.command("list")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--status", default=None, help="Filter by run status.")
@click.option("--schema", "schema_id", default=None, help="Filter by schema definition ID.")
@click.option("--limit", type=int, default=None, help="Max results to return.")
@click.option("--offset", type=int, default=None, help="Offset for pagination.")
@click.pass_context
def runs_list(ctx, project_flag, status, schema_id, limit, offset):
    """List runs for a project."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    params: dict = {}
    if status is not None:
        params["status"] = status
    if schema_id is not None:
        params["schemaId"] = schema_id
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    resp = fz.get(f"/api/projects/{pid}/runs", params=params)
    data = resp.json()

    format_output(data, columns=RUN_LIST_COLUMNS, fmt=fmt, quiet=quiet)


# ── get ─────────────────────────────────────────────────────────────────────

@runs_group.command("get")
@click.argument("run_id")
@click.pass_context
def runs_get(ctx, run_id):
    """Show details for a specific run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.get(f"/api/runs/{run_id}")
    data = resp.json()

    format_output(data, fmt=fmt, quiet=quiet)


# ── watch ───────────────────────────────────────────────────────────────────

@runs_group.command("watch")
@click.argument("run_id")
@click.pass_context
def runs_watch(ctx, run_id):
    """Watch a run's progress in real time."""
    from rich.live import Live
    from rich.table import Table

    fz = ctx.obj["client"]
    poll_interval = ctx.obj["config"].run_poll_interval

    def _build_table(run: dict, events: list) -> Table:
        """Build a rich table showing run status."""
        status = run.get("status", "unknown")
        progress = run.get("progressPercent", 0) or 0
        progress_msg = run.get("progressMessage", "")
        result_count = run.get("resultCount", 0)
        doc_count = run.get("documentSnapshotCount", 0)
        error_msg = run.get("errorMessage", "")
        started = run.get("startedAt", "")
        duration = run.get("durationSeconds", "")

        table = Table(title=f"Run {run_id}", show_header=False, expand=True)
        table.add_column("Field", style="bold cyan", width=20)
        table.add_column("Value")

        table.add_row("Status", status)

        # Progress bar representation
        bar_width = 30
        filled = int(bar_width * progress / 100) if progress else 0
        bar = "\u2588" * filled + "\u2591" * (bar_width - filled)
        table.add_row("Progress", f"[{bar}] {progress}%")

        if progress_msg:
            table.add_row("Message", progress_msg)
        table.add_row("Documents", str(doc_count))
        table.add_row("Results", str(result_count))
        if started:
            table.add_row("Started", str(started))
        if duration:
            table.add_row("Duration", f"{duration}s")
        if error_msg:
            table.add_row("Error", error_msg)

        # Recent events
        if events:
            table.add_row("", "")
            table.add_row("Recent Events", "")
            for evt in events[-5:]:
                evt_status = evt.get("status", "")
                evt_msg = evt.get("message", "")
                evt_time = evt.get("createdAt", "")
                table.add_row(f"  {evt_time}", f"{evt_status}: {evt_msg}")

        return table

    try:
        with Live(refresh_per_second=1) as live:
            while True:
                resp = fz.get(f"/api/runs/{run_id}")
                run = resp.json()
                status = run.get("status")

                # Fetch recent events
                events_resp = fz.get(
                    f"/api/runs/{run_id}/status-events",
                    params={"limit": 5},
                )
                events_data = events_resp.json()
                events = events_data.get("items", []) if isinstance(events_data, dict) else events_data

                live.update(_build_table(run, events))

                if status in ("completed", "failed", "cancelled"):
                    break

                time.sleep(poll_interval)
    except KeyboardInterrupt:
        click.echo(f"\nStopped watching. Run {run_id} continues on server.", err=True)
        return

    # Print final status to stderr
    if status == "completed":
        click.echo(f"Run {run_id} completed successfully.", err=True)
    elif status == "failed":
        click.echo(f"Run {run_id} failed: {run.get('errorMessage', '')}", err=True)
    elif status == "cancelled":
        click.echo(f"Run {run_id} was cancelled.", err=True)


# ── cancel ──────────────────────────────────────────────────────────────────

@runs_group.command("cancel")
@click.argument("run_id")
@click.pass_context
def runs_cancel(ctx, run_id):
    """Cancel a running extraction run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.post(f"/api/runs/{run_id}/cancel")
    data = resp.json()

    if not quiet:
        click.echo(f"Run cancelled: {run_id}", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


# ── results ─────────────────────────────────────────────────────────────────

@runs_group.command("results")
@click.argument("run_id")
@click.option("--result", "result_id", default=None, help="Specific result ID.")
@click.option("--limit", type=int, default=None, help="Max results to return.")
@click.option("--offset", type=int, default=None, help="Offset for pagination.")
@click.pass_context
def runs_results(ctx, run_id, result_id, limit, offset):
    """List or get results for a run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    if result_id:
        # Fetch a single result
        resp = fz.get(f"/api/runs/{run_id}/results/{result_id}")
        data = resp.json()
        format_output(data, fmt=fmt, quiet=quiet)
    else:
        # List all results
        params: dict = {}
        if limit is not None:
            params["limit"] = limit
        if offset is not None:
            params["offset"] = offset

        resp = fz.get(f"/api/runs/{run_id}/results", params=params)
        data = resp.json()

        # Truncate the data field only for table display — keep full payload for machine formats
        if fmt == "table" and isinstance(data, dict) and "items" in data:
            import copy
            display_data = copy.deepcopy(data)
            for item in display_data["items"]:
                if "data" in item and item["data"] is not None:
                    preview = json_mod.dumps(item["data"], default=str)
                    item["data"] = preview[:57] + "..." if len(preview) > 60 else preview
        else:
            display_data = data

        format_output(display_data, columns=RESULT_LIST_COLUMNS, fmt=fmt, quiet=quiet)


# ── documents ───────────────────────────────────────────────────────────────

@runs_group.command("documents")
@click.argument("run_id")
@click.pass_context
def runs_documents(ctx, run_id):
    """List document snapshots for a run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.get(f"/api/runs/{run_id}/documents")
    data = resp.json()

    format_output(data, columns=DOCUMENT_LIST_COLUMNS, fmt=fmt, quiet=quiet)


# ── events ──────────────────────────────────────────────────────────────────

@runs_group.command("events")
@click.argument("run_id")
@click.option("--limit", type=int, default=None, help="Max events to return.")
@click.option("--offset", type=int, default=None, help="Offset for pagination.")
@click.pass_context
def runs_events(ctx, run_id, limit, offset):
    """List status events for a run."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    params: dict = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    resp = fz.get(f"/api/runs/{run_id}/status-events", params=params)
    data = resp.json()

    format_output(data, columns=EVENT_LIST_COLUMNS, fmt=fmt, quiet=quiet)
