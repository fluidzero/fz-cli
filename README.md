# fz — FluidZero CLI

The official command-line interface for the [FluidZero](https://fluidzero.ai) document intelligence platform.

Manage projects, upload documents, define schemas, execute extraction runs, search results, and more — all from your terminal.

## Installation

### Homebrew (macOS)

```bash
brew install fluidzero/tap/fz
```

### pip

```bash
pip install fluidzero-cli
```

### From source

```bash
git clone https://github.com/fluidzero/fz-cli.git
cd fz-cli
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Quick Start

```bash
# Authenticate (opens browser for device-code confirmation)
fz auth login

# List projects
fz projects list

# Upload documents and wait for processing
fz documents upload -p <project-id> *.pdf --wait

# Run extraction with a schema
fz runs create -p <project-id> --schema <schema-id> --wait

# Search extracted data
fz search "quarterly revenue" -p <project-id>
```

## Commands

| Command | Description |
|---------|-------------|
| `fz auth` | Login, logout, status, print token |
| `fz projects` | Create, list, get, update, delete projects |
| `fz documents` | Upload, list, get, delete, download documents |
| `fz schemas` | Manage schemas and schema versions |
| `fz prompts` | Manage prompts and prompt versions |
| `fz runs` | Create, list, watch, cancel runs; view results |
| `fz search` | Search extracted data (global or project-scoped) |
| `fz webhooks` | Manage webhook endpoints and deliveries |
| `fz api-keys` | Create, list, revoke API keys for CI/CD |
| `fz run` | Composite: upload documents + run extraction |
| `fz batch` | Batch process a directory of documents |

## Global Flags

Global flags go **before** the subcommand (Click convention):

```bash
fz -o json projects list       # JSON output
fz -o csv projects list        # CSV output
fz -q runs create ...          # Quiet mode
fz -v documents upload ...     # Verbose (shows HTTP requests)
fz -p <id> documents list      # Set default project
```

## Configuration

Settings are resolved in order (later wins):

1. Defaults
2. `~/.config/fluidzero/config.toml` (global)
3. `.fluidzero.toml` (project-local)
4. Environment variables
5. CLI flags

### Environment Variables

| Variable | Description |
|----------|-------------|
| `FZ_API_URL` | API base URL |
| `FZ_PROJECT_ID` | Default project ID |
| `FZ_OUTPUT` | Default output format (`table`, `json`, `jsonl`, `csv`) |
| `FZ_CLIENT_ID` | M2M client ID (CI/CD) |
| `FZ_CLIENT_SECRET` | M2M client secret (CI/CD) |
| `NO_COLOR` | Disable colored output |

### Config File Example

```toml
# ~/.config/fluidzero/config.toml
[defaults]
api_url = "https://api.fluidzero.ai"
project = "e94af89d-..."
output = "table"

[upload]
concurrency = 4
retry_attempts = 3
```

## Authentication

### Interactive (browser device flow)

```bash
fz auth login    # Shows a code, opens browser for confirmation
fz auth status   # Check current identity and token expiry
fz auth logout   # Remove stored credentials
```

### Machine-to-Machine (CI/CD)

```bash
export FZ_CLIENT_ID=client_01K...
export FZ_CLIENT_SECRET=124e12a...
fz projects list   # Uses M2M auth automatically
```

Create API keys with `fz api-keys create "My CI Key"`.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

Copyright 2025 Force Platforms Inc.
