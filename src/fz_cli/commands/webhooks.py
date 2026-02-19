"""Webhook commands: create, list, get, update, delete, test, deliveries."""

from __future__ import annotations

import json as json_mod
import sys

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output


# ── Table column definitions ────────────────────────────────────────────────

WEBHOOK_LIST_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("url", "URL"),
    ("eventTypes", "EVENTS"),
    ("isActive", "ACTIVE"),
    ("createdAt", "CREATED"),
]

DELIVERY_LIST_COLUMNS = [
    ("id", "ID"),
    ("eventType", "EVENT"),
    ("success", "SUCCESS"),
    ("statusCode", "STATUS"),
    ("attemptNumber", "ATTEMPT"),
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


def _parse_json_option(value: str | None, option_name: str) -> dict | None:
    """Parse a JSON string option, exiting on invalid JSON."""
    if value is None:
        return None
    try:
        parsed = json_mod.loads(value)
        if not isinstance(parsed, dict):
            click.echo(f"Error: {option_name} must be a JSON object.", err=True)
            sys.exit(EXIT_GENERAL_ERROR)
        return parsed
    except json_mod.JSONDecodeError as exc:
        click.echo(f"Error: Invalid JSON for {option_name}: {exc}", err=True)
        sys.exit(EXIT_GENERAL_ERROR)


# ── Click group ─────────────────────────────────────────────────────────────

@click.group("webhooks")
def webhooks_group():
    """Manage webhook configurations."""
    pass


# ── create ──────────────────────────────────────────────────────────────────

@webhooks_group.command("create")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.option("--name", required=True, help="Webhook name.")
@click.option("--url", "webhook_url", required=True, help="Webhook delivery URL (https).")
@click.option("--description", default=None, help="Webhook description.")
@click.option("--secret", default=None, help="Signing secret for request verification.")
@click.option(
    "--event", "event_types", multiple=True,
    help="Event types to subscribe to (repeatable, e.g. --event run.completed --event run.failed).",
)
@click.option("--max-retries", type=int, default=None, help="Max delivery retry attempts.")
@click.option("--retry-interval", type=int, default=None, help="Seconds between retries.")
@click.option("--headers", "custom_headers_json", default=None, help="Custom headers as JSON object.")
@click.option("--include-results", is_flag=True, default=False, help="Include run results in payload.")
@click.pass_context
def webhooks_create(
    ctx,
    project_flag,
    name,
    webhook_url,
    description,
    secret,
    event_types,
    max_retries,
    retry_interval,
    custom_headers_json,
    include_results,
):
    """Create a new webhook configuration."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    payload: dict = {
        "name": name,
        "url": webhook_url,
    }

    if description is not None:
        payload["description"] = description
    if secret is not None:
        payload["secret"] = secret
    if event_types:
        payload["eventTypes"] = list(event_types)
    if max_retries is not None:
        payload["maxRetries"] = max_retries
    if retry_interval is not None:
        payload["retryIntervalSeconds"] = retry_interval
    if include_results:
        payload["includeResults"] = True

    custom_headers = _parse_json_option(custom_headers_json, "--headers")
    if custom_headers is not None:
        payload["customHeaders"] = custom_headers

    resp = fz.post(f"/api/projects/{pid}/webhooks", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Webhook created: {data.get('id')}", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


# ── list ────────────────────────────────────────────────────────────────────

@webhooks_group.command("list")
@click.option("-p", "--project", "project_flag", default=None, help="Project ID.")
@click.pass_context
def webhooks_list(ctx, project_flag):
    """List webhooks for a project."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]
    pid = _resolve_project_id(ctx, project_flag)

    resp = fz.get(f"/api/projects/{pid}/webhooks")
    data = resp.json()

    format_output(data, columns=WEBHOOK_LIST_COLUMNS, fmt=fmt, quiet=quiet)


# ── get ─────────────────────────────────────────────────────────────────────

@webhooks_group.command("get")
@click.argument("webhook_id")
@click.pass_context
def webhooks_get(ctx, webhook_id):
    """Show details for a webhook configuration."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.get(f"/api/webhooks/{webhook_id}")
    data = resp.json()

    format_output(data, fmt=fmt, quiet=quiet)


# ── update ──────────────────────────────────────────────────────────────────

@webhooks_group.command("update")
@click.argument("webhook_id")
@click.option("--name", default=None, help="New webhook name.")
@click.option("--url", "webhook_url", default=None, help="New delivery URL.")
@click.option("--description", default=None, help="New description.")
@click.option("--secret", default=None, help="New signing secret.")
@click.option(
    "--event", "event_types", multiple=True,
    help="Replace event types (repeatable).",
)
@click.option("--max-retries", type=int, default=None, help="Max delivery retry attempts.")
@click.option("--retry-interval", type=int, default=None, help="Seconds between retries.")
@click.option("--headers", "custom_headers_json", default=None, help="Custom headers as JSON object.")
@click.option("--include-results/--no-include-results", default=None, help="Include run results in payload.")
@click.option("--active/--inactive", "is_active", default=None, help="Enable or disable the webhook.")
@click.pass_context
def webhooks_update(
    ctx,
    webhook_id,
    name,
    webhook_url,
    description,
    secret,
    event_types,
    max_retries,
    retry_interval,
    custom_headers_json,
    include_results,
    is_active,
):
    """Update a webhook configuration."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    payload: dict = {}

    if name is not None:
        payload["name"] = name
    if webhook_url is not None:
        payload["url"] = webhook_url
    if description is not None:
        payload["description"] = description
    if secret is not None:
        payload["secret"] = secret
    if event_types:
        payload["eventTypes"] = list(event_types)
    if max_retries is not None:
        payload["maxRetries"] = max_retries
    if retry_interval is not None:
        payload["retryIntervalSeconds"] = retry_interval
    if include_results is not None:
        payload["includeResults"] = include_results
    if is_active is not None:
        payload["isActive"] = is_active

    custom_headers = _parse_json_option(custom_headers_json, "--headers")
    if custom_headers is not None:
        payload["customHeaders"] = custom_headers

    if not payload:
        click.echo("Error: Provide at least one field to update.", err=True)
        sys.exit(EXIT_GENERAL_ERROR)

    resp = fz.put(f"/api/webhooks/{webhook_id}", json=payload)
    data = resp.json()

    if not quiet:
        click.echo(f"Webhook updated: {webhook_id}", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


# ── delete ──────────────────────────────────────────────────────────────────

@webhooks_group.command("delete")
@click.argument("webhook_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def webhooks_delete(ctx, webhook_id, confirm):
    """Delete a webhook configuration."""
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    if not confirm:
        click.confirm(f"Delete webhook {webhook_id}? This cannot be undone", abort=True)

    fz.delete(f"/api/webhooks/{webhook_id}")

    if not quiet:
        click.echo(f"Webhook deleted: {webhook_id}", err=True)


# ── test ────────────────────────────────────────────────────────────────────

@webhooks_group.command("test")
@click.argument("webhook_id")
@click.pass_context
def webhooks_test(ctx, webhook_id):
    """Send a test delivery to a webhook."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.post(f"/api/webhooks/{webhook_id}/test")
    data = resp.json()

    if not quiet:
        success = data.get("success", False)
        status_code = data.get("statusCode", "")
        if success:
            click.echo(f"Test delivery successful (HTTP {status_code}).", err=True)
        else:
            error = data.get("error", "unknown error")
            click.echo(f"Test delivery failed: {error} (HTTP {status_code}).", err=True)

    format_output(data, fmt=fmt, quiet=quiet)


# ── deliveries ──────────────────────────────────────────────────────────────

@webhooks_group.command("deliveries")
@click.argument("webhook_id")
@click.option("--success", "success_filter", type=bool, default=None, help="Filter by success (true/false).")
@click.option("--event-type", default=None, help="Filter by event type.")
@click.option("--limit", type=int, default=None, help="Max deliveries to return.")
@click.option("--offset", type=int, default=None, help="Offset for pagination.")
@click.pass_context
def webhooks_deliveries(ctx, webhook_id, success_filter, event_type, limit, offset):
    """List delivery attempts for a webhook."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    params: dict = {}
    if success_filter is not None:
        params["success"] = str(success_filter).lower()
    if event_type is not None:
        params["eventType"] = event_type
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset

    resp = fz.get(f"/api/webhooks/{webhook_id}/deliveries", params=params)
    data = resp.json()

    format_output(data, columns=DELIVERY_LIST_COLUMNS, fmt=fmt, quiet=quiet)
