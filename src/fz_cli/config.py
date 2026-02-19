"""Configuration loading: .fluidzero.toml (CWD) > ~/.config/fluidzero/config.toml > defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from .constants import (
    DEFAULT_API_URL,
    DEFAULT_AUTHKIT_SUBDOMAIN,
    DEFAULT_OAUTH_CLIENT_ID,
    GLOBAL_CONFIG_PATH,
    LOCAL_CONFIG_FILE,
    UPLOAD_CONCURRENCY,
    UPLOAD_RETRY_ATTEMPTS,
    RUN_POLL_INTERVAL,
    RUN_TIMEOUT,
)


@dataclass
class FZConfig:
    """Resolved configuration."""

    api_url: str = DEFAULT_API_URL
    project: str | None = None
    output: str = "table"
    authkit_subdomain: str = DEFAULT_AUTHKIT_SUBDOMAIN
    oauth_client_id: str = DEFAULT_OAUTH_CLIENT_ID

    # Upload
    upload_concurrency: int = UPLOAD_CONCURRENCY
    upload_retry_attempts: int = UPLOAD_RETRY_ATTEMPTS

    # Runs
    run_poll_interval: int = RUN_POLL_INTERVAL
    run_timeout: int = RUN_TIMEOUT


def _read_toml(path: Path) -> dict:
    """Read a TOML file, returning empty dict if missing/invalid."""
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text())
    except Exception:
        return {}


def load_config() -> FZConfig:
    """Load config by merging local > global > env > defaults."""
    global_cfg = _read_toml(GLOBAL_CONFIG_PATH)
    local_cfg = _read_toml(Path.cwd() / LOCAL_CONFIG_FILE)

    # Merge: local overrides global
    merged = {}
    for section in ("defaults", "upload", "runs"):
        merged[section] = {**global_cfg.get(section, {}), **local_cfg.get(section, {})}

    # Also merge top-level keys from local config (e.g. project = "...")
    for key in ("project", "schema"):
        if key in local_cfg:
            merged["defaults"][key] = local_cfg[key]

    defaults = merged.get("defaults", {})
    upload = merged.get("upload", {})
    runs = merged.get("runs", {})

    cfg = FZConfig()

    # Defaults section
    cfg.api_url = os.getenv("FZ_API_URL") or defaults.get("api_url", cfg.api_url)
    cfg.project = os.getenv("FZ_PROJECT_ID") or defaults.get("project", cfg.project)
    cfg.output = os.getenv("FZ_OUTPUT") or defaults.get("output", cfg.output)

    # AuthKit / OAuth
    cfg.authkit_subdomain = (
        os.getenv("FZ_AUTHKIT_SUBDOMAIN")
        or global_cfg.get("authkit_subdomain")
        or cfg.authkit_subdomain
    )
    cfg.oauth_client_id = (
        os.getenv("FZ_OAUTH_CLIENT_ID")
        or global_cfg.get("oauth_client_id")
        or cfg.oauth_client_id
    )

    # Upload section
    cfg.upload_concurrency = upload.get("concurrency", cfg.upload_concurrency)
    cfg.upload_retry_attempts = upload.get("retry_attempts", cfg.upload_retry_attempts)

    # Runs section
    cfg.run_poll_interval = runs.get("poll_interval", cfg.run_poll_interval)
    cfg.run_timeout = runs.get("timeout", cfg.run_timeout)

    return cfg
