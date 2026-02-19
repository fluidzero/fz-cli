"""Root CLI group and global flags."""

from __future__ import annotations

import sys

import click

from . import __version__
from .client import FZClient
from .config import FZConfig, load_config


@click.group()
@click.version_option(__version__, prog_name="fz")
@click.option("--api-url", envvar="FZ_API_URL", default=None, help="API base URL.")
@click.option("-p", "--project", envvar="FZ_PROJECT_ID", default=None, help="Default project ID.")
@click.option(
    "-o", "--output", "output_format",
    envvar="FZ_OUTPUT",
    type=click.Choice(["table", "json", "jsonl", "csv"], case_sensitive=False),
    default=None,
    help="Output format.",
)
@click.option("-q", "--quiet", is_flag=True, default=False, help="Suppress non-essential output.")
@click.option("-v", "--verbose", is_flag=True, default=False, help="Show HTTP requests and timing.")
@click.option("--no-color", is_flag=True, envvar="NO_COLOR", default=False, help="Disable colored output.")
@click.pass_context
def cli(ctx, api_url, project, output_format, quiet, verbose, no_color):
    """FluidZero CLI — manage projects, documents, schemas, runs, and more."""
    ctx.ensure_object(dict)

    cfg = load_config()

    # CLI flags override config
    resolved_api_url = api_url or cfg.api_url
    resolved_output = output_format or cfg.output
    resolved_project = project or cfg.project

    ctx.obj["config"] = cfg
    ctx.obj["api_url"] = resolved_api_url
    ctx.obj["project_id"] = resolved_project
    ctx.obj["output_format"] = resolved_output
    ctx.obj["quiet"] = quiet
    ctx.obj["verbose"] = verbose
    ctx.obj["no_color"] = no_color

    # Lazy client — created on first use by commands that need it
    ctx.obj["client"] = FZClient(api_url=resolved_api_url, verbose=verbose)


# ── Register command groups ─────────────────────────────────────────────────

from .commands.auth import auth_group
from .commands.projects import projects_group
from .commands.documents import documents_group
from .commands.schemas import schemas_group
from .commands.prompts import prompts_group
from .commands.runs import runs_group
from .commands.search import search_cmd
from .commands.webhooks import webhooks_group
from .commands.batch import run_cmd, batch_cmd
from .commands.api_keys import api_keys_group

cli.add_command(auth_group)
cli.add_command(projects_group)
cli.add_command(documents_group)
cli.add_command(schemas_group)
cli.add_command(prompts_group)
cli.add_command(runs_group)
cli.add_command(search_cmd)
cli.add_command(webhooks_group)
cli.add_command(run_cmd)
cli.add_command(batch_cmd)
cli.add_command(api_keys_group)


def main():
    cli(auto_envvar_prefix="FZ")


if __name__ == "__main__":
    main()
