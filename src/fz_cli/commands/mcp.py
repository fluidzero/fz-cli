"""`fz mcp setup` — connect the fluidzero MCP server to your agent in one step.

Mints an M2M API key (requires an interactive `fz auth login` session) and
prints ready-to-paste configuration for Claude Code, Claude Desktop, and
Cursor — no dashboard round-trip, no hand-assembled JSON.
"""

from __future__ import annotations

import json as json_mod
import socket

import click


@click.group("mcp")
def mcp_group():
    """Set up the fluidzero MCP server for your agent."""
    pass


@mcp_group.command("setup")
@click.option("--name", default=None,
              help="Name for the API key (default: 'MCP - <hostname>').")
@click.option("--client", "client_kind",
              type=click.Choice(["claude-code", "claude-desktop", "cursor", "all"]),
              default="all", show_default=True,
              help="Which agent client to print config for.")
@click.pass_context
def mcp_setup(ctx, name: str | None, client_kind: str):
    """Create an API key and print copy-paste MCP config for your agent.

    Requires an interactive login (`fz auth login`) because API keys are
    minted with your user session. The secret is shown ONLY ONCE — the
    printed config already contains it.
    """
    fz = ctx.obj["client"]
    api_url = ctx.obj["api_url"]

    key_name = name or f"MCP - {socket.gethostname()}"
    data = fz.post("/api/api-keys", json={"name": key_name, "scopes": ["*"]}).json()
    client_id = data.get("clientId", "")
    client_secret = data.get("clientSecret", "")
    if not client_id or not client_secret:
        raise click.ClickException("API key creation did not return credentials.")

    click.echo(f"Created API key '{key_name}' for the MCP server.", err=True)
    click.echo("The secret below is shown ONLY ONCE — this config already includes it.\n", err=True)

    if client_kind in ("claude-code", "all"):
        click.echo("# Claude Code — run this:")
        click.echo(
            "claude mcp add fluidzero \\\n"
            f"  --env FZ_API_URL={api_url} \\\n"
            f"  --env FZ_CLIENT_ID={client_id} \\\n"
            f"  --env FZ_CLIENT_SECRET={client_secret} \\\n"
            "  -- fz-mcp\n"
        )

    if client_kind in ("claude-desktop", "cursor", "all"):
        target = {
            "claude-desktop": "Claude Desktop (claude_desktop_config.json)",
            "cursor": "Cursor (.cursor/mcp.json)",
            "all": "Claude Desktop (claude_desktop_config.json) / Cursor (.cursor/mcp.json)",
        }[client_kind]
        block = {
            "mcpServers": {
                "fluidzero": {
                    "command": "fz-mcp",
                    "env": {
                        "FZ_API_URL": api_url,
                        "FZ_CLIENT_ID": client_id,
                        "FZ_CLIENT_SECRET": client_secret,
                    },
                }
            }
        }
        click.echo(f"# {target} — merge this into the config file:")
        click.echo(json_mod.dumps(block, indent=2))
        click.echo("")

    click.echo(
        "Install the server with `pip install fluidzero-mcp` if you haven't. "
        "Revoke this key anytime with `fz api-keys revoke`.",
        err=True,
    )
