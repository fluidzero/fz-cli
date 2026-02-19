"""Composite workflow commands: fz run (upload + create + wait) and fz batch."""

from __future__ import annotations

import json as json_mod
import sys
import time
from pathlib import Path

import click

from ..constants import EXIT_GENERAL_ERROR, EXIT_RUN_FAILED, EXIT_TIMEOUT
from ..output import format_output
from ..upload import upload_files


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


def _wait_for_run(ctx: click.Context, fz, run_id: str, timeout: int | None = None) -> dict:
    """Poll a run until it reaches a terminal status or times out."""
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
                click.echo("", err=True)
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


def _create_run(fz, project_id: str, payload: dict) -> dict:
    """Create a run and return the response dict."""
    resp = fz.post(f"/api/projects/{project_id}/runs", json=payload)
    return resp.json()


def _fetch_all_results(fz, run_id: str) -> list[dict]:
    """Fetch all results for a run, paginating through all pages."""
    results: list[dict] = []
    offset = 0
    limit = 100

    while True:
        resp = fz.get(f"/api/runs/{run_id}/results", params={"offset": offset, "limit": limit})
        data = resp.json()
        items = data.get("items", []) if isinstance(data, dict) else data
        results.extend(items)

        total = data.get("total", 0) if isinstance(data, dict) else len(items)
        if offset + limit >= total or not items:
            break
        offset += limit

    return results


# ── Supported file extensions for batch scanning ────────────────────────────

_SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif",
    ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt",
}


# ── fz run ──────────────────────────────────────────────────────────────────

@click.command("run")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--schema", "schema_id", required=True, help="Schema definition ID.")
@click.option("--schema-version", "schema_version_id", default=None, help="Schema version ID.")
@click.option("--prompt", "prompt_id", default=None, help="Prompt definition ID.")
@click.option("--webhook", "webhook_id", default=None, help="Webhook config ID.")
@click.option("--params", "params_json", default=None, help="Input parameters as JSON string.")
@click.option("--external-id", "external_id", default=None, help="External run ID for tracking.")
@click.option(
    "--upload", "upload_paths", multiple=True, type=click.Path(exists=True),
    help="File(s) to upload before creating the run (repeatable).",
)
@click.option("--wait", is_flag=True, default=False, help="Wait for run completion and show results.")
@click.option(
    "--timeout", type=int, default=None,
    help="Timeout in seconds when waiting (default from config).",
)
@click.pass_context
def run_cmd(
    ctx,
    project_flag,
    schema_id,
    schema_version_id,
    prompt_id,
    webhook_id,
    params_json,
    external_id,
    upload_paths,
    wait,
    timeout,
):
    """Upload files, create a run, and optionally wait for results.

    This is a convenience command that combines upload + run creation.
    If no --upload files are given it simply creates and optionally
    waits for a run.
    """
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    # ── Step 1: Upload files if provided ────────────────────────────────
    if upload_paths:
        file_paths = [Path(p) for p in upload_paths]
        if not quiet:
            click.echo(f"Uploading {len(file_paths)} file(s)...", err=True)
        upload_files(
            fz,
            pid,
            file_paths,
            wait=True,  # wait for documents to be ready before running
            concurrency=ctx.obj["config"].upload_concurrency,
            max_retries=ctx.obj["config"].upload_retry_attempts,
        )

    # ── Step 2: Build run payload ───────────────────────────────────────
    payload: dict = {"schemaDefinitionId": schema_id}

    if schema_version_id is not None:
        payload["schemaVersionId"] = schema_version_id
    if prompt_id is not None:
        payload["promptDefinitionId"] = prompt_id
    if webhook_id is not None:
        payload["webhookConfigId"] = webhook_id
    if external_id is not None:
        payload["externalRunId"] = external_id

    if params_json is not None:
        try:
            payload["inputParameters"] = json_mod.loads(params_json)
        except json_mod.JSONDecodeError as exc:
            click.echo(f"Error: Invalid JSON for --params: {exc}", err=True)
            sys.exit(EXIT_GENERAL_ERROR)

    # ── Step 3: Create run ──────────────────────────────────────────────
    run = _create_run(fz, pid, payload)
    run_id = run.get("id")

    if not quiet:
        click.echo(f"Run created: {run_id}", err=True)

    # ── Step 4: Optionally wait and show results ────────────────────────
    if wait:
        run = _wait_for_run(ctx, fz, run_id, timeout=timeout)

        # Fetch and display results
        results = _fetch_all_results(fz, run_id)
        result_count = len(results)

        if not quiet:
            click.echo(f"Run completed with {result_count} result(s).", err=True)

        format_output(
            {"items": results, "total": result_count},
            fmt=fmt,
            quiet=quiet,
        )
    else:
        format_output(run, fmt=fmt, quiet=quiet)


# ── fz batch ────────────────────────────────────────────────────────────────

@click.command("batch")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--schema", "schema_id", required=True, help="Schema definition ID.")
@click.option(
    "--dir", "input_dir", required=True,
    type=click.Path(exists=True, file_okay=False, dir_okay=True),
    help="Directory of files to process.",
)
@click.option("--batch-size", type=click.IntRange(min=1), default=10, show_default=True, help="Files per batch.")
@click.option("--concurrency", type=click.IntRange(min=1), default=2, show_default=True, help="Upload concurrency.")
@click.option(
    "--output", "output_file", default=None,
    type=click.Path(dir_okay=False),
    help="Write results to this file as JSONL.",
)
@click.option(
    "--timeout", type=int, default=None,
    help="Timeout in seconds per run (default from config).",
)
@click.pass_context
def batch_cmd(
    ctx,
    project_flag,
    schema_id,
    input_dir,
    batch_size,
    concurrency,
    output_file,
    timeout,
):
    """Batch-process a directory of files: upload, run, collect results.

    Scans DIR for supported files, uploads in batches of --batch-size,
    creates a run after each batch, waits for completion, and collects
    all results into an output JSONL file.
    """
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    # ── Scan directory for supported files ──────────────────────────────
    dir_path = Path(input_dir)
    all_files = sorted(
        f for f in dir_path.iterdir()
        if f.is_file() and f.suffix.lower() in _SUPPORTED_EXTENSIONS
    )

    if not all_files:
        click.echo(f"No supported files found in {input_dir}.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    if not quiet:
        click.echo(f"Found {len(all_files)} file(s) in {input_dir}.", err=True)

    # ── Split into batches ──────────────────────────────────────────────
    batches: list[list[Path]] = []
    for i in range(0, len(all_files), batch_size):
        batches.append(all_files[i : i + batch_size])

    if not quiet:
        click.echo(
            f"Processing in {len(batches)} batch(es) of up to {batch_size} files.",
            err=True,
        )

    # ── Process each batch ──────────────────────────────────────────────
    # When streaming to a file, avoid holding all results in memory simultaneously.
    all_results: list[dict] = []  # only populated when no output_file
    total_result_count = 0
    output_handle = None

    try:
        if output_file:
            output_handle = open(output_file, "w")

        for batch_idx, batch_files in enumerate(batches, start=1):
            if not quiet:
                click.echo(
                    f"\n--- Batch {batch_idx}/{len(batches)} "
                    f"({len(batch_files)} files) ---",
                    err=True,
                )

            # Upload batch
            upload_files(
                fz,
                pid,
                batch_files,
                wait=True,
                concurrency=concurrency,
                max_retries=ctx.obj["config"].upload_retry_attempts,
            )

            # Create run
            payload = {"schemaDefinitionId": schema_id}
            run = _create_run(fz, pid, payload)
            run_id = run.get("id")

            if not quiet:
                click.echo(f"Run created: {run_id}", err=True)

            # Wait for run completion
            run = _wait_for_run(ctx, fz, run_id, timeout=timeout)

            # Collect results
            results = _fetch_all_results(fz, run_id)
            total_result_count += len(results)

            if not quiet:
                click.echo(
                    f"Batch {batch_idx} complete: {len(results)} result(s).",
                    err=True,
                )

            if output_handle:
                # Stream to file immediately — no need to keep in memory
                for result in results:
                    output_handle.write(json_mod.dumps(result, default=str) + "\n")
                output_handle.flush()
            else:
                all_results.extend(results)

    finally:
        if output_handle:
            output_handle.close()

    # ── Summary ─────────────────────────────────────────────────────────
    if not quiet:
        click.echo(
            f"\nBatch processing complete: {len(all_files)} file(s), "
            f"{len(batches)} batch(es), {total_result_count} total result(s).",
            err=True,
        )
        if output_file:
            click.echo(f"Results written to {output_file}", err=True)
