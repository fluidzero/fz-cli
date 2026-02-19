"""API key commands: create, list, get, revoke."""

from __future__ import annotations

import sys

import click

from ..constants import EXIT_GENERAL_ERROR
from ..output import format_output

API_KEY_LIST_COLUMNS = [
    ("id", "ID"),
    ("name", "NAME"),
    ("clientId", "CLIENT ID"),
    ("keyPrefix", "PREFIX"),
    ("scopes", "SCOPES"),
    ("createdAt", "CREATED"),
]


@click.group("api-keys")
def api_keys_group():
    """Manage M2M API keys for CI/CD and service integrations."""
    pass


@api_keys_group.command("create")
@click.argument("name")
@click.option(
    "--scope", "scopes", multiple=True,
    help="Permission scopes (repeatable). Defaults to all standard scopes.",
)
@click.option("--expires-at", default=None, help="Expiry timestamp (ISO 8601).")
@click.pass_context
def api_keys_create(ctx, name: str, scopes: tuple, expires_at: str | None):
    """Create a new API key.

    The client_id and client_secret are shown ONLY ONCE in the output.
    Save them immediately.
    """
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    payload: dict = {"name": name}
    if scopes:
        payload["scopes"] = list(scopes)
    if expires_at:
        payload["expiresAt"] = expires_at

    resp = fz.post("/api/api-keys", json=payload)
    data = resp.json()

    # Always show credentials regardless of format — they're one-time-only
    client_id = data.get("clientId", data.get("client_id", ""))
    client_secret = data.get("clientSecret", data.get("client_secret", ""))

    if fmt == "json":
        # Always emit JSON output — credentials are one-time-only and must not be silenced
        format_output(data, fmt=fmt, quiet=False)
    else:
        click.echo(f"API key created: {data.get('key', {}).get('name', name)}", err=True)
        click.echo("", err=True)
        click.echo(f"  Client ID:     {client_id}")
        click.echo(f"  Client Secret: {client_secret}")
        click.echo("", err=True)
        click.echo("Save these credentials now — the secret cannot be retrieved again.", err=True)


@api_keys_group.command("list")
@click.pass_context
def api_keys_list(ctx):
    """List all API keys for your organization."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.get("/api/api-keys")
    data = resp.json()

    format_output(data, columns=API_KEY_LIST_COLUMNS, fmt=fmt, quiet=quiet)


@api_keys_group.command("get")
@click.argument("key_id")
@click.pass_context
def api_keys_get(ctx, key_id: str):
    """Show details for an API key."""
    fz = ctx.obj["client"]
    fmt = ctx.obj["output_format"]
    quiet = ctx.obj["quiet"]

    resp = fz.get(f"/api/api-keys/{key_id}")
    data = resp.json()

    format_output(data, fmt=fmt, quiet=quiet)


@api_keys_group.command("revoke")
@click.argument("key_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@click.pass_context
def api_keys_revoke(ctx, key_id: str, confirm: bool):
    """Revoke an API key. This cannot be undone."""
    fz = ctx.obj["client"]
    quiet = ctx.obj["quiet"]

    if not confirm:
        click.confirm(f"Revoke API key {key_id}? This cannot be undone", abort=True)

    fz.delete(f"/api/api-keys/{key_id}")

    if not quiet:
        click.echo(f"API key revoked: {key_id}", err=True)
