"""API error → exit code mapping with user-friendly messages and hints."""

from __future__ import annotations

import sys

import click
import httpx

from .constants import (
    EXIT_AUTH_FAILURE,
    EXIT_CONFLICT,
    EXIT_GENERAL_ERROR,
    EXIT_NETWORK_ERROR,
    EXIT_NOT_FOUND,
    EXIT_PERMISSION_DENIED,
)

# (exit_code, default_message, hint_template)
_STATUS_MAP: dict[int, tuple[int, str, str | None]] = {
    401: (EXIT_AUTH_FAILURE, "Authentication failed", "Run `fz auth login` to re-authenticate."),
    403: (EXIT_PERMISSION_DENIED, "Permission denied", None),
    404: (EXIT_NOT_FOUND, "Resource not found", None),
    409: (EXIT_CONFLICT, "Conflict", None),
}


def _extract_detail(response: httpx.Response) -> str | None:
    """Try to extract the 'detail' field from a JSON error response."""
    try:
        body = response.json()
        detail = body.get("detail")
        if isinstance(detail, str):
            return detail
        if isinstance(detail, dict):
            return detail.get("message", str(detail))
        return None
    except Exception:
        return None


def handle_api_error(response: httpx.Response) -> None:
    """Map an HTTP error response to a CLI error message and exit."""
    status = response.status_code
    detail = _extract_detail(response)

    if status in _STATUS_MAP:
        exit_code, default_msg, hint = _STATUS_MAP[status]
        message = detail or f"{default_msg} ({status})"
    elif 400 <= status < 500:
        exit_code = EXIT_GENERAL_ERROR
        message = detail or f"Client error ({status})"
        hint = None
    else:
        exit_code = EXIT_GENERAL_ERROR
        message = detail or f"Server error ({status})"
        hint = "The API returned an unexpected error. Try again later."

    # Special 401 hints based on WWW-Authenticate header
    if status == 401:
        www_auth = response.headers.get("www-authenticate", "")
        if "revoked" in www_auth.lower():
            message = "Authentication failed — token has been revoked"
            hint = "Create new credentials and run `fz auth login`."
        elif "expired" in www_auth.lower():
            message = "Authentication failed — token has expired"
            hint = "Run `fz auth login` to re-authenticate."

    click.echo(f"Error: {message}", err=True)
    if hint:
        click.echo(f"Hint: {hint}", err=True)
    sys.exit(exit_code)


def handle_network_error(exc: httpx.RequestError) -> None:
    """Handle connection/DNS/timeout errors."""
    click.echo(f"Error: Network error — {exc}", err=True)
    click.echo("Hint: Check your network connection and API URL.", err=True)
    sys.exit(EXIT_NETWORK_ERROR)
