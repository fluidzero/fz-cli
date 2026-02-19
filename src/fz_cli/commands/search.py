"""Search command: query documents across the platform."""

from __future__ import annotations

import sys

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output


@click.command("search")
@click.argument("query")
@click.option("-p", "--project", "project_flag", default=None, help="Scope search to a project.")
@click.option(
    "--no-citations", is_flag=True, default=False,
    help="Omit citation details from output.",
)
@click.pass_context
def search_cmd(ctx, query: str, project_flag: str | None, no_citations: bool):
    """Search documents using natural language.

    QUERY is the natural-language search string.
    """
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    include_citations = not no_citations
    payload = {
        "query": query,
        "includeCitations": include_citations,
    }

    # Use project-scoped endpoint if a project is specified
    project_id = project_flag or ctx.obj.get("project_id")
    if project_id:
        resp = fz.post(f"/api/projects/{project_id}/search", json=payload)
    else:
        resp = fz.post("/api/search", json=payload)

    data = resp.json()

    # For JSON/JSONL/CSV output, delegate to the standard formatter
    if fmt in ("json", "jsonl", "csv"):
        format_output(data, fmt=fmt, quiet=quiet)
        return

    # Table/human-readable output
    if quiet:
        return

    results = data.get("results", [])
    if not results:
        click.echo("No results found.")
        return

    for i, result in enumerate(results, start=1):
        content = result.get("content", "")
        citations = result.get("citations", [])

        click.echo(f"--- Result {i} ---")
        click.echo(content)
        click.echo()

        if include_citations and citations:
            click.echo("  Citations:")
            for cit in citations:
                doc = cit.get("doc", "")
                page = cit.get("page", "")
                excerpt = cit.get("excerpt", "")
                url = cit.get("url", "")

                parts = []
                if doc:
                    parts.append(doc)
                if page:
                    parts.append(f"p.{page}")
                source_label = ", ".join(parts) if parts else "unknown source"

                click.echo(f"    [{source_label}]", nl=False)
                if url:
                    click.echo(f"  {url}", nl=False)
                click.echo()

                if excerpt:
                    # Indent excerpt lines
                    for line in excerpt.splitlines():
                        click.echo(f"      {line}")
            click.echo()
