"""Constants for the FluidZero CLI."""

import os
from pathlib import Path

# ── Exit codes (per CLI_DESIGN.md) ──────────────────────────────────────────
EXIT_SUCCESS = 0
EXIT_GENERAL_ERROR = 1
EXIT_AUTH_FAILURE = 2
EXIT_PERMISSION_DENIED = 3
EXIT_NOT_FOUND = 4
EXIT_CONFLICT = 5
EXIT_RUN_FAILED = 6
EXIT_TIMEOUT = 7
EXIT_NETWORK_ERROR = 10

# ── API defaults ────────────────────────────────────────────────────────────
DEFAULT_API_URL = "https://api-staging.fluidzero.ai"

# ── OAuth / AuthKit (public PKCE values, not secrets) ───────────────────────
DEFAULT_AUTHKIT_SUBDOMAIN = "euphoric-grape-60-staging"
DEFAULT_OAUTH_CLIENT_ID = "client_01KGA8ECKMDH8GWPZR00QGPTBZ"

# ── File paths ──────────────────────────────────────────────────────────────
CONFIG_DIR = Path(os.getenv("XDG_CONFIG_HOME", Path.home() / ".config")) / "fluidzero"
CREDENTIALS_PATH = CONFIG_DIR / "credentials.json"
GLOBAL_CONFIG_PATH = CONFIG_DIR / "config.toml"
LOCAL_CONFIG_FILE = ".fluidzero.toml"

# ── Upload defaults ─────────────────────────────────────────────────────────
UPLOAD_CONCURRENCY = 5
UPLOAD_RETRY_ATTEMPTS = 3
UPLOAD_DIRECT_THRESHOLD = 10 * 1024 * 1024  # 10 MB

# ── Run defaults ────────────────────────────────────────────────────────────
RUN_POLL_INTERVAL = 2  # seconds
RUN_TIMEOUT = 600  # seconds

# ── OAuth callback ──────────────────────────────────────────────────────────
OAUTH_CALLBACK_TIMEOUT = 120  # seconds
