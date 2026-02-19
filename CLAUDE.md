# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

`fz-cli` is the official command-line interface for the FluidZero document intelligence platform. It wraps the Escape Velocity REST API (FastAPI backend) with an ergonomic Click-based CLI supporting project management, document upload, schema versioning, async run execution, search, webhooks, API key management, and composite workflows.

## Tech Stack

- Python 3.11+ with Click 8.x CLI framework
- httpx (sync) for HTTP requests
- tabulate for table output
- rich for progress bars and live displays
- PyJWT for token decode (no verification)
- tomllib (stdlib) for TOML config

## Common Commands

```bash
# Setup
cd fz-cli
python -m venv .venv
source .venv/bin/activate
pip install -e .

# Verify installation
fz --help
fz --version

# Authentication (browser device flow)
fz auth login          # WorkOS device flow — shows code, opens browser
fz auth status         # Show identity, org, role, token expiry, API URL
fz auth logout         # Remove stored credentials
fz auth token          # Print JWT to stdout (pipe-friendly)

# API key management (M2M)
fz api-keys create "My CI Key"       # Create key — shows client_id + secret ONCE
fz api-keys list                     # List org keys
fz api-keys revoke <key-id> --confirm

# Using M2M credentials (CI/CD)
export FZ_CLIENT_ID=client_01K...
export FZ_CLIENT_SECRET=124e12a...
export FZ_API_URL=http://localhost:8000
fz projects list  # Uses M2M auth automatically

# Example workflows
fz projects list
fz documents upload -p <project-id> *.pdf --wait
fz runs create -p <project-id> --schema <schema-id> --wait
fz run -p <project-id> --schema <schema-id> --upload *.pdf --wait  # composite
fz search "quarterly revenue" -p <project-id>

# Global flags come BEFORE subcommand (Click convention)
fz -o json projects list       # JSON output
fz -o csv projects list        # CSV output
fz -q projects list            # Quiet (no output)
fz -v projects list            # Verbose (shows HTTP requests on stderr)
```

## Architecture

### Source Layout

```
src/fz_cli/
├── main.py              # Root @click.group, global flags, command registration
├── constants.py         # Exit codes (0-10), paths, OAuth defaults (subdomain, client_id)
├── config.py            # TOML config merging: .fluidzero.toml > ~/.config/fluidzero/config.toml > env > defaults
├── client.py            # FZClient: authenticated httpx wrapper, auto-refresh (browser) + auto re-exchange (M2M)
├── output.py            # format_output(): table/json/jsonl/csv formatters
├── errors.py            # HTTP status → exit code mapping with user-friendly hints
├── upload.py            # Multipart upload engine: 4-step presigned URL flow, parallel parts
├── auth/
│   ├── browser.py       # WorkOS device authorization flow (RFC 8628) — NOT PKCE redirect
│   ├── credentials.py   # Read/write ~/.config/fluidzero/credentials.json (0600), stores client_id
│   ├── token.py         # TokenManager: load, expiry check, refresh via backend proxy
│   └── m2m.py           # client_credentials exchange for CI/CD
└── commands/
    ├── auth.py          # fz auth login|status|logout|token
    ├── projects.py      # fz projects list|create|get|update|delete
    ├── documents.py     # fz documents upload|list|get|delete|download
    ├── schemas.py       # fz schemas CRUD + fz schemas versions create|list|get|diff
    ├── prompts.py       # fz prompts CRUD + fz prompts versions create|list|get (--text-only)
    ├── runs.py          # fz runs create|list|get|watch|cancel|results|documents|events
    ├── search.py        # fz search <query> (global or project-scoped)
    ├── webhooks.py      # fz webhooks create|list|get|update|delete|test|deliveries
    ├── api_keys.py      # fz api-keys create|list|get|revoke
    └── batch.py         # fz run (composite upload+run) + fz batch (directory processing)
```

### Key Design Patterns

- **Click context object** (`ctx.obj`): All commands access shared state — `client` (FZClient), `config` (FZConfig), `api_url`, `project_id`, `output_format`, `quiet`, `verbose`
- **Lazy auth resolution**: `FZClient._resolve_auth()` runs on first API call, not at startup. Credential priority: `FZ_CLIENT_ID`+`FZ_CLIENT_SECRET` env vars (M2M) > credentials file (browser flow)
- **Project ID resolution**: Each command group has `_resolve_project_id(ctx, explicit_flag)` that falls back through: explicit arg > `ctx.obj["project_id"]` (from `-p` flag, env var, or config) > error
- **Output formatting**: All commands call `format_output(data, columns=..., fmt=..., quiet=...)`. The `_unwrap()` helper normalizes bare lists, paginated `{items, total}` envelopes, and single dicts
- **Status messages to stderr**: All informational output uses `click.echo(..., err=True)` so stdout stays clean for piping (`fz auth token`, `fz runs results --json | jq`)
- **Exit codes**: 0=success, 1=general, 2=auth, 3=forbidden, 4=not found, 5=conflict, 6=run failed, 7=timeout, 10=network error
- **Global flags before subcommand**: `-o`, `-q`, `-v`, `-p` are root-group options per Click convention (e.g. `fz -o json projects list`, NOT `fz projects list -o json`)

### Authentication & Token Refresh

Three auth modes, each with automatic token lifecycle management:

#### 1. Browser Device Flow (interactive)

`fz auth login` uses the [WorkOS Device Authorization Flow (RFC 8628)](https://workos.com/docs/authkit/cli-auth):

1. `POST https://api.workos.com/user_management/authorize/device` → device_code + user_code
2. User confirms code in browser at `https://{subdomain}.authkit.app/device?user_code=...`
3. CLI polls `POST https://api.workos.com/user_management/authenticate` with device_code
4. Receives `access_token` + `refresh_token`, saved to `~/.config/fluidzero/credentials.json`

**Token refresh** (transparent, on every API call):
- TokenManager checks expiry 60s before `exp` claim
- Refreshes via backend proxy: `POST {api_url}/oauth/token` with `grant_type=refresh_token&source=device`
- Backend routes `source=device` to WorkOS User Management (`/user_management/authenticate`)
- WorkOS rotates the refresh token on each use — new tokens saved to credentials file
- On 401 response, retries once after refresh

**Why `source=device`**: Device-flow tokens are issued by WorkOS User Management API, not the AuthKit OAuth2 endpoint. The backend's `/oauth/token` proxy uses the `source` hint to route to the correct WorkOS endpoint. Without `source=device`, the proxy tries AuthKit first and falls back to UM automatically.

#### 2. M2M API Keys (CI/CD)

Set `FZ_CLIENT_ID` + `FZ_CLIENT_SECRET` env vars. On first API call:

1. `POST {api_url}/oauth/token` with `grant_type=client_credentials` + caller's `client_id`/`client_secret`
2. Backend proxies to AuthKit `/oauth2/token` → returns short-lived JWT (no refresh token)
3. Token stored in memory only (not persisted to disk)

**Token re-exchange** (transparent): When M2M token expires, FZClient automatically re-exchanges `client_id`/`client_secret` for a fresh token. No refresh token involved — it's a full re-exchange. On 401, also retries with re-exchange.

#### 3. Swagger UI / Frontend (AuthKit OAuth2)

Not used by the CLI directly, but the backend proxy supports it for completeness:
- `POST /oauth/token` with `grant_type=refresh_token` (no `source` param)
- Backend proxies to AuthKit `/oauth2/token`

#### Credentials File

`~/.config/fluidzero/credentials.json` (permissions `0600`):

```json
{
  "access_token": "eyJ...",
  "refresh_token": "AthaZXNE...",
  "expires_at": 1771486528,
  "api_url": "http://localhost:8000",
  "client_id": "client_01KGA8ECKMDH8GWPZR00QGPTBZ"
}
```

The `client_id` is stored so the token manager can refresh via the backend proxy without needing it from config. This is the WorkOS environment client ID (public, not a secret).

### Backend `/oauth/token` Proxy

The escape-velocity backend's `/oauth/token` endpoint (`main.py`) is a unified token proxy that routes to the correct WorkOS endpoint:

| Grant Type | `source` Param | WorkOS Endpoint | Use Case |
|------------|---------------|-----------------|----------|
| `authorization_code` | — | `authkit.app/oauth2/token` | Swagger UI PKCE |
| `refresh_token` | `device` | `api.workos.com/user_management/authenticate` | CLI device-flow token refresh |
| `refresh_token` | (none) | `authkit.app/oauth2/token`, fallback to UM | Swagger/frontend, auto-detects |
| `client_credentials` | — | `authkit.app/oauth2/token` | M2M API key exchange |

The proxy adds server-side secrets (`WORKOS_OAUTH_CLIENT_ID`, `WORKOS_API_KEY`) so clients never need them.

### Upload System

The 4-step presigned URL flow (matches backend `routers/uploads.py`):

1. `POST /api/projects/{id}/uploads/init` → presigned URLs, part size, upload ID
2. `PUT` parts to S3 in parallel (ThreadPoolExecutor, configurable concurrency)
3. `POST /api/uploads/{id}/parts` → report each ETag
4. `POST /api/uploads/{id}/complete` → finalize, get Document back

Files < 10MB use single PUT (no multipart). Resume support via `POST /api/uploads/{id}/resume`.

### Backend API Contract

The CLI targets the Escape Velocity API (see `../escape-velocity/CLAUDE.md`):

- All request/response bodies use **camelCase** JSON (e.g. `schemaDefinitionId`, `fileName`, `fileSizeBytes`)
- Paginated responses: `{"items": [...], "total": N, "offset": N, "limit": N}`
- Auth: `Authorization: Bearer <JWT>` header on all requests
- 401 responses include `WWW-Authenticate: Bearer error="invalid_token", error_description="..."` for programmatic detection

### Configuration

Merge order (later wins): defaults → `~/.config/fluidzero/config.toml` → `.fluidzero.toml` (CWD) → env vars → CLI flags

```toml
# ~/.config/fluidzero/config.toml
[defaults]
api_url = "https://api-staging.fluidzero.ai"
project = "e94af89d-..."
output = "table"

[upload]
concurrency = 4
retry_attempts = 3

[runs]
poll_interval = 2
timeout = 600
```

### OAuth Constants

Hardcoded in `constants.py` (public PKCE values, not secrets — safe to commit):

- `DEFAULT_AUTHKIT_SUBDOMAIN = "euphoric-grape-60-staging"` — WorkOS AuthKit subdomain
- `DEFAULT_OAUTH_CLIENT_ID = "client_01KGA8ECKMDH8GWPZR00QGPTBZ"` — WorkOS environment client ID

Overridable via `FZ_AUTHKIT_SUBDOMAIN` and `FZ_OAUTH_CLIENT_ID` env vars or config.toml keys for switching staging/prod.

### Adding a New Command

1. Create `src/fz_cli/commands/<name>.py` with a `@click.group("<name>")` or `@click.command("<name>")`
2. Use `ctx.obj["client"]` for API calls, `format_output()` for output
3. Add `_resolve_project_id()` helper if project-scoped
4. Import and register in `main.py` via `cli.add_command()`
5. Follow camelCase for API JSON fields, snake_case for Python

### Environment Variables

| Variable | Description |
|----------|-------------|
| `FZ_API_URL` | API base URL (default: `https://api-staging.fluidzero.ai`) |
| `FZ_PROJECT_ID` | Default project ID |
| `FZ_OUTPUT` | Default output format (table/json/jsonl/csv) |
| `FZ_CLIENT_ID` | M2M client ID — triggers M2M auth mode (CI/CD) |
| `FZ_CLIENT_SECRET` | M2M client secret — required with `FZ_CLIENT_ID` |
| `FZ_AUTHKIT_SUBDOMAIN` | AuthKit subdomain override |
| `FZ_OAUTH_CLIENT_ID` | OAuth client ID override |
| `NO_COLOR` | Disable colored output |
