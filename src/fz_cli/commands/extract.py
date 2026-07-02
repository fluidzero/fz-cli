"""`fz extract` — the one-command extraction workflow.

Upload files (optional), get a schema from wherever is easiest (a natural-
language description, a JSON Schema file/string, an existing schema, or a
pinned version), run a v2 extraction, and print the structured result.

This is the flagship composite and it rides the v2 eager path end-to-end —
unlike `fz run`, which uses the legacy v1 pipeline.
"""

from __future__ import annotations

import glob as glob_mod
import json as json_mod
import sys
from pathlib import Path

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output
from ..upload import upload_files
from .extractions import (
    _resolve_project_id,
    _wait_for_extraction,
    resolve_latest_schema_version,
    warn_if_result_empty,
)


def _expand_files(patterns: tuple[str, ...]) -> list[Path]:
    paths: list[Path] = []
    for pattern in patterns:
        p = Path(pattern)
        if p.is_file():
            paths.append(p.resolve())
            continue
        matches = sorted(Path(m) for m in glob_mod.glob(pattern, recursive=True))
        found = [m.resolve() for m in matches if m.is_file()]
        if not found:
            click.echo(f"Warning: No files matched '{pattern}'", err=True)
        paths.extend(found)
    # De-dup preserving order
    seen: set[Path] = set()
    unique = [p for p in paths if not (p in seen or seen.add(p))]
    return unique


@click.command("extract")
@click.argument("files", nargs=-1, required=False)
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--describe", "describe_text", default=None,
              help="Describe the fields you want in plain language — a schema is generated for you.")
@click.option("--schema", "schema_id", default=None,
              help="Existing schema ID (latest version used automatically).")
@click.option("--schema-version", "schema_version_id", default=None, help="Pin an exact schema version ID.")
@click.option("--schema-file", "schema_file", type=click.Path(exists=True), default=None,
              help="Path to a JSON Schema file.")
@click.option("--schema-json", "schema_inline", default=None, help="Inline JSON Schema string.")
@click.option("--external-id", "external_id", default=None, help="External ID for idempotent replay.")
@click.option("--timeout", type=int, default=None, help="Seconds to wait for completion.")
@click.pass_context
def extract_cmd(
    ctx, files, project_flag, describe_text, schema_id, schema_version_id,
    schema_file, schema_inline, external_id, timeout,
):
    """Upload documents (optional), run an extraction, and print the result.

    One command, start to finish:

        fz extract specs.pdf --describe "compressive strength, mix design"

    FILES are uploaded and indexed first; omit them to extract from documents
    already in the project. Provide the schema however is easiest: --describe
    (generated for you), --schema, --schema-version, --schema-file, or
    --schema-json.
    """
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    sources = (describe_text, schema_id, schema_version_id, schema_file, schema_inline)
    if sum(x is not None for x in sources) != 1:
        click.echo(
            "Error: tell me what to extract — exactly one of --describe, --schema, "
            "--schema-version, --schema-file, or --schema-json.",
            err=True,
        )
        sys.exit(EXIT_GENERAL_ERROR)

    # 1) Upload + index any files given.
    if files:
        paths = _expand_files(files)
        if not paths:
            click.echo("Error: no files to upload.", err=True)
            sys.exit(EXIT_GENERAL_ERROR)
        if not quiet:
            click.echo(f"Uploading {len(paths)} file(s)...", err=True)
        upload_files(
            fz, pid, paths,
            wait=True,  # extraction needs indexed documents
            resume=False,
            concurrency=ctx.obj["config"].upload_concurrency,
            max_retries=ctx.obj["config"].upload_retry_attempts,
        )

    # 2) Resolve the schema from whichever source was given.
    inline = None
    if describe_text is not None:
        if not quiet:
            click.echo("Generating schema from your description...", err=True)
        described = fz.post(
            f"/api/projects/{pid}/schemas/describe",
            json={"newInstruction": describe_text},
        ).json()
        inline = described.get("schema")
        if not inline:
            click.echo("Error: schema generation returned no schema.", err=True)
            sys.exit(EXIT_GENERAL_ERROR)
    elif schema_file is not None:
        with open(schema_file) as fh:
            inline = json_mod.load(fh)
    elif schema_inline is not None:
        try:
            inline = json_mod.loads(schema_inline)
        except json_mod.JSONDecodeError as exc:
            click.echo(f"Error: Invalid JSON for --schema-json: {exc}", err=True)
            sys.exit(EXIT_GENERAL_ERROR)
    elif schema_id is not None:
        schema_version_id = resolve_latest_schema_version(fz, schema_id)

    # 3) Run the extraction (v2 eager path) and wait.
    payload: dict = {}
    if schema_version_id is not None:
        payload["schemaVersionId"] = schema_version_id
    else:
        payload["schema"] = inline
    if external_id is not None:
        payload["externalId"] = external_id

    ext = fz.post(f"/api/v2/projects/{pid}/extractions", json=payload).json()
    extraction_id = ext.get("id") or ext.get("extractionId")
    if not quiet:
        click.echo(f"Extraction started: {extraction_id}", err=True)

    _wait_for_extraction(ctx, extraction_id, timeout)

    # 4) Print the structured result.
    result = fz.get(f"/api/v2/extractions/{extraction_id}/result").json()
    warn_if_result_empty(result)
    format_output(result, fmt=fmt, quiet=quiet)
