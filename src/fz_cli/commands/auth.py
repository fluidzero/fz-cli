"""Auth commands: login, status, logout, token."""

import sys
import time

import click

from ..auth.browser import browser_login
from ..auth.credentials import delete_credentials
from ..auth.token import TokenManager
from ..constants import EXIT_AUTH_FAILURE


@click.group("auth")
def auth_group():
    """Manage authentication."""
    pass


@auth_group.command("login")
@click.pass_context
def auth_login(ctx):
    """Authenticate via browser OAuth flow."""
    cfg = ctx.obj["config"]
    api_url = ctx.obj["api_url"]

    tokens = browser_login(
        api_url=api_url,
        authkit_subdomain=cfg.authkit_subdomain,
        oauth_client_id=cfg.oauth_client_id,
    )

    mgr = TokenManager(api_url)

    # Derive expires_in from JWT exp claim if not in response
    expires_in = tokens.get("expires_in")
    if not expires_in:
        claims = mgr._decode(tokens["access_token"])
        expires_in = claims.get("exp", int(time.time()) + 300) - int(time.time())

    mgr.set_tokens(
        access_token=tokens["access_token"],
        refresh_token=tokens.get("refresh_token"),
        expires_in=expires_in,
        client_id=cfg.oauth_client_id,
    )

    # Show identity
    claims = mgr.decode_claims()
    user_id = claims.get("sub", "unknown")
    org_id = claims.get("org_id", "none")
    click.echo(f"Authenticated as {user_id}")
    if org_id and org_id != "none":
        click.echo(f"Organization: {org_id}")
    click.echo("Credentials saved to ~/.config/fluidzero/credentials.json")


@auth_group.command("status")
@click.pass_context
def auth_status(ctx):
    """Show current authentication status."""
    api_url = ctx.obj["api_url"]
    mgr = TokenManager(api_url)

    if not mgr.load_from_credentials():
        click.echo("Not authenticated. Run `fz auth login`.", err=True)
        sys.exit(EXIT_AUTH_FAILURE)

    claims = mgr.decode_claims()
    user_id = claims.get("sub", "unknown")
    org_id = claims.get("org_id", "\u2014")
    role = claims.get("role", "\u2014")
    permissions = claims.get("permissions", [])
    exp = claims.get("exp", 0)

    # Calculate time until expiry
    remaining = exp - int(time.time())
    if remaining > 0:
        mins = remaining // 60
        token_status = f"valid (expires in {mins}m)"
    else:
        token_status = "expired"

    click.echo(f"User:        {user_id}")
    click.echo(f"Org:         {org_id}")
    click.echo(f"Role:        {role}")
    if permissions:
        click.echo(f"Permissions: {', '.join(permissions)}")
    click.echo(f"Token:       {token_status}")
    click.echo(f"API:         {mgr.api_url}")


@auth_group.command("logout")
def auth_logout():
    """Remove stored credentials."""
    if delete_credentials():
        click.echo("Credentials removed.")
    else:
        click.echo("No credentials found.")


@auth_group.command("token")
@click.pass_context
def auth_token(ctx):
    """Print current access token to stdout (pipe-friendly)."""
    api_url = ctx.obj["api_url"]
    mgr = TokenManager(api_url)

    if not mgr.load_from_credentials():
        click.echo("Not authenticated. Run `fz auth login`.", err=True)
        sys.exit(EXIT_AUTH_FAILURE)

    token = mgr.get_access_token()
    if not token:
        click.echo("Token expired and refresh failed. Run `fz auth login`.", err=True)
        sys.exit(EXIT_AUTH_FAILURE)

    # Print only the token to stdout (no newline for easy piping)
    click.echo(token, nl=True)
