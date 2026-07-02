# Submittal Review System — Technical Design & Implementation

> Cross-project compliance validation: compare construction requirements against vendor tech specs using AI agents on Modal, with full persistence in Escape Velocity and real-time UI in Fennec UI.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Service-by-Service Changes](#service-by-service-changes)
4. [Data Model](#data-model)
5. [API Endpoints](#api-endpoints)
6. [Modal Execution](#modal-execution)
7. [Frontend Integration](#frontend-integration)
8. [Authentication & Secrets](#authentication--secrets)
9. [Event Pipeline](#event-pipeline)
10. [Files Changed](#files-changed)
11. [Database Migrations](#database-migrations)
12. [Deployment Checklist](#deployment-checklist)
13. [Known Limitations](#known-limitations)

---

## System Overview

Submittal reviews are a **new entity type** in FluidZero, separate from extraction runs. They compare two projects:

- **Specs Project**: Contains vendor technical specification documents (e.g., HVAC unit datasheets)
- **Requirements Project**: Contains construction requirement documents (e.g., UFGS specifications)

The Nexus agent reads both projects via the Knowledge Graph (Neo4j + MongoDB), extracts testable requirements, validates each against the specs, and produces a `ComplianceReport` with individual `ComplianceLineItem` findings.

### Key Design Decisions

1. **Dedicated EV tables** — Submittal reviews do NOT use the existing `runs` table. They have their own `submittal_reviews`, `submittal_review_line_items`, and `submittal_review_events` tables. This avoids the `schema_definition_id`/`schema_version_id` NOT NULL constraints that extraction runs require.

2. **Modal execution** — The Nexus agent runs on Modal (not in-process on FluidDoc), using the Claude Agent SDK with a Claude Max subscription token (`CLAUDE_CODE_OAUTH_TOKEN`).

3. **Polling, not SSE** — The frontend creates a review in EV, dispatches to Modal (fire-and-forget), and polls EV for status updates. This matches the pattern used by extraction runs. No SSE streaming from FluidDoc.

4. **Raw event preservation** — Every Claude Agent SDK message (SystemMessage, AssistantMessage, ToolUseBlock, etc.) is stored as-is in `submittal_review_events.event_metadata` JSONB. Events are batched (3-second flush interval) to avoid DB connection pool exhaustion.

5. **Callback-based completion** — Modal sends status updates to EV's `/api/submittal-reviews/{id}/status` endpoint (NOT `/api/runs/`). On completion, line items are persisted atomically with the status transition.

---

## Architecture

```
fennec-ui (Next.js 16)
    │
    │  1. POST /api/backend/projects/{specsProjectId}/submittal-reviews
    │     → Creates SubmittalReview in EV (status: pending)
    │
    │  2. POST /api/backend/submittal-reviews/{reviewId}/dispatch
    │     → Fire-and-forget POST to Modal /validate endpoint
    │     → Does NOT await response (Modal runs for minutes)
    │
    │  3. Poll every 5s:
    │     GET /api/backend/submittal-reviews/{reviewId}
    │     GET /api/backend/submittal-reviews/{reviewId}/events?offset=N
    │     → Parse raw SDK events from eventMetadata.batch[]
    │     → Feed through nexus-stream-parser for UI rendering
    │
    ▼
Escape Velocity (FastAPI)
    │
    │  POST /api/submittal-reviews/{id}/status  ← callbacks from Modal
    │  GET  /api/submittal-reviews/{id}         ← frontend polling
    │  GET  /api/submittal-reviews/{id}/events  ← frontend polling
    │  GET  /api/submittal-reviews/{id}/line-items ← results
    │  GET  /api/submittal-reviews              ← org-wide listing
    │
    ▼
Modal (fluiddoc-nexus app)
    │
    │  POST /validate
    │  ├─ Phase 1: Requirements extraction (1 SDK client, Sonnet)
    │  ├─ Phase 2: Parallel validation (N SDK clients, Sonnet)
    │  └─ Phase 3: Report compilation (Python, no SDK)
    │
    │  Each event → buffer → flush every 3s → POST to EV /api/submittal-reviews/{id}/status
    │  On completion → POST with lineItems + executiveSummary + scores
    │
    ▼
Knowledge Graph (Neo4j + MongoDB + Turbopuffer)
    │
    │  19 MCP tools for document navigation:
    │  Layer 0: Schema & traversal (Neo4j Cypher)
    │  Layer 1: Discovery (MongoDB)
    │  Layer 2: Content reading (MongoDB + Neo4j)
    │  Layer 3: Search (regex + graph + semantic embeddings)
    │  Layer 4: VLM fallback (Gemini Vision)
    │  Layer 5: Compliance (save_compliance_result)
    │
    ▼
S3 (page images for evidence bounding boxes)
```

---

## Service-by-Service Changes

### 1. Escape Velocity (Python/FastAPI)

**New models** (3 tables):
- `SubmittalReview` — parent record with dual project FKs, compliance scores, status lifecycle
- `SubmittalReviewLineItem` — per-requirement findings with evidence JSONB
- `SubmittalReviewEvent` — immutable status event audit trail

**New router**: `src/api/routers/submittal_reviews.py` — 8 endpoints (see API section)

**New enum**: `SubmittalReviewStatus` (pending, running, completed, failed, cancelled)

**Modified**: `PipelineMode` enum now includes `NEXUS` value, `Project` model has `submittal_review_count`

### 2. FluidDoc (Python/FastAPI)

**New Modal app**: `fluiddoc/modal/nexus_sandbox.py` — `fluiddoc-nexus` app on Modal
- Image: Debian slim + Node.js 20 + `claude-code@latest` + all Python deps
- Secrets: `fluiddoc-claude-max`, `fluiddoc-neo4j`, `fluiddoc-mongodb`, `fluiddoc-gemini`, `fluiddoc-aws`
- Endpoints: `POST /validate`, `GET /health`
- 30-minute timeout
- Callback bridging with 3-second event batching

**New schemas**: `fluiddoc/modal/nexus_schemas.py` — `NexusModalRequest`

**Modified config**: `core/config.py` — added `modal_nexus_enabled`, `modal_nexus_endpoint_url`, `modal_nexus_app_name`

**Modified SQS worker**: `worker/sqs_worker.py` — added `_dispatch_nexus_to_modal()` for `pipeline == "nexus"` routing

**Modified agent config**: `agents/nexus/agent_config.py` — changed `permission_mode` from `bypassPermissions` to `acceptEdits` (required for root containers)

### 3. Fennec UI (TypeScript/Next.js 16)

**New types**: `lib/api/types.ts` — `SubmittalReview`, `SubmittalReviewCreate`, `SubmittalReviewLineItem`, `SubmittalReviewEvent`, list response types

**New server API functions**: `lib/api/server.ts` — `createSubmittalReview`, `listSubmittalReviews`, `getSubmittalReview`, `getSubmittalReviewLineItems`, `cancelSubmittalReview`

**New proxy routes** (8 routes in `app/api/backend/`):
- `projects/[projectId]/submittal-reviews/route.ts` — POST create, GET list
- `submittal-reviews/route.ts` — GET org-wide list (single API call)
- `submittal-reviews/[reviewId]/route.ts` — GET detail
- `submittal-reviews/[reviewId]/status/route.ts` — POST callback proxy
- `submittal-reviews/[reviewId]/line-items/route.ts` — GET results
- `submittal-reviews/[reviewId]/events/route.ts` — GET audit trail
- `submittal-reviews/[reviewId]/cancel/route.ts` — POST cancel
- `submittal-reviews/[reviewId]/dispatch/route.ts` — POST trigger Modal

**Modified hook**: `lib/hooks/use-nexus-stream.ts` — rewrote from SSE streaming to EV polling:
- `startStream()`: Create review in EV → dispatch to Modal (fire-and-forget) → poll EV every 5s
- `hydrateFromReviewId()`: Load historical events from EV, replay through parser, continue polling if still running
- `cancelRun()`: Cancels via EV endpoint (not FluidDoc)
- Raw event parsing: Unpacks `eventMetadata.batch[]` arrays, feeds through `nexus-stream-parser.ts`

**Modified pages**:
- `submittal-reviews/page.tsx` — Added "Past Reviews" section with org-wide listing from EV (single API call)
- `submittal-reviews/compare/page.tsx` — Added `<Suspense>` wrapper for `useSearchParams`, `tab` URL param, `review_id` priority logic

---

## Data Model

### `submittal_reviews` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| project_id | UUID FK → projects | Specs project (CASCADE) |
| requirements_project_id | UUID FK → projects | Requirements project (SET NULL) |
| status | ENUM | pending → running → completed/failed/cancelled |
| model_used | VARCHAR(100) | e.g., claude-sonnet-4-5-20250929 |
| input_parameters | JSONB | maxRequirements, maxTurns, etc. |
| overall_compliance_score | FLOAT | 0.0-1.0 |
| total_requirements | INT | Denormalized count |
| compliant_count | INT | |
| non_compliant_count | INT | |
| partially_compliant_count | INT | |
| not_found_count | INT | |
| not_applicable_count | INT | |
| line_item_count | INT | Denormalized |
| executive_summary | TEXT | Agent-generated narrative |
| methodology | TEXT | How validation was performed |
| error_message | TEXT | For failed reviews |
| error_code | VARCHAR(100) | |
| progress_percent | INT | Denormalized from events |
| progress_message | TEXT | |
| duration_seconds | FLOAT | |
| tool_calls_used | INT | |
| external_run_id | VARCHAR(255) | Optional correlation ID |
| owner_id | VARCHAR(255) | WorkOS user ID |
| org_id | VARCHAR(255) | WorkOS org ID |
| created_at | TIMESTAMPTZ | server_default=now() |
| updated_at | TIMESTAMPTZ | onupdate=now() |
| started_at | TIMESTAMPTZ | Set when status → running |
| completed_at | TIMESTAMPTZ | Set when terminal |

**Indexes**: project_id, requirements_project_id, status, owner_id, created_at

### `submittal_review_line_items` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| submittal_review_id | UUID FK | CASCADE |
| sequence_number | INT | Unique per review |
| requirement_id | VARCHAR(100) | e.g., REQ-001 |
| requirement_text | TEXT | |
| category | VARCHAR(100) | mechanical, electrical, fire_safety, etc. |
| status | VARCHAR(50) | compliant/non_compliant/partially_compliant/not_found/not_applicable |
| confidence | FLOAT | 0.0-1.0 |
| reasoning | TEXT | Agent's comparison narrative |
| requirement_source | JSONB | {source_document, source_page, section_id, section_heading, bbox} |
| evidence | JSONB | [{source_document, vendor, page_number, excerpt, bbox, relevance}] |
| gaps | JSONB | ["gap description", ...] for non-compliant items |
| created_at | TIMESTAMPTZ | Immutable |

### `submittal_review_events` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID PK | |
| submittal_review_id | UUID FK | CASCADE |
| status | VARCHAR(50) | Status at this event |
| previous_status | VARCHAR(50) | |
| message | TEXT | e.g., "nexus:AssistantMessage (+6 events)" |
| event_metadata | JSONB | **Raw SDK events**: `{batch: [...events], count: N}` |
| sequence_number | INT | Unique per review, monotonic |
| created_by | VARCHAR(255) | "fluiddoc-nexus-worker-v1" |
| created_at | TIMESTAMPTZ | Immutable, no updated_at |

---

## API Endpoints

### Escape Velocity

| Method | Endpoint | Auth | Purpose |
|--------|----------|------|---------|
| POST | `/api/projects/{id}/submittal-reviews` | WorkOS JWT | Create review |
| GET | `/api/projects/{id}/submittal-reviews` | WorkOS JWT | List reviews for project |
| GET | `/api/submittal-reviews` | WorkOS JWT | List ALL reviews for org |
| GET | `/api/submittal-reviews/{id}` | WorkOS JWT | Get review detail |
| POST | `/api/submittal-reviews/{id}/status` | None (M2M) | Status callback from Modal |
| GET | `/api/submittal-reviews/{id}/line-items` | WorkOS JWT | List compliance findings |
| GET | `/api/submittal-reviews/{id}/events` | WorkOS JWT | Audit trail |
| POST | `/api/submittal-reviews/{id}/cancel` | WorkOS JWT | Cancel review |

### Modal

| Method | Endpoint | Purpose |
|--------|----------|---------|
| GET | `/health` | Health check |
| POST | `/validate` | Run 3-phase Nexus validation |

### Status Callback Body (Modal → EV)

**Progress events** (during execution):
```json
{
  "status": "running",
  "message": "nexus:AssistantMessage (+6 events)",
  "createdBy": "fluiddoc-nexus-worker-v1",
  "eventMetadata": {
    "batch": [
      {"type": "AssistantMessage", "content": [...], "model": "...", "error": null, "parent_tool_use_id": null},
      {"type": "UserMessage", "content": [...], "uuid": "...", "parent_tool_use_id": "...", "tool_use_result": "..."},
      ...
    ],
    "count": 6
  }
}
```

**Completion event** (with line items):
```json
{
  "status": "completed",
  "message": "Nexus validated 25 requirements: 21 compliant, 2 non-compliant, score=84%",
  "createdBy": "fluiddoc-nexus-worker-v1",
  "executiveSummary": "...",
  "methodology": "...",
  "overallComplianceScore": 0.84,
  "modelUsed": "claude-sonnet-4-5-20250929",
  "durationSeconds": 87.5,
  "toolCallsUsed": 143,
  "lineItems": [
    {
      "requirementId": "REQ-001",
      "requirementText": "HVAC units shall have minimum SEER rating of 16",
      "category": "mechanical",
      "status": "compliant",
      "confidence": 0.95,
      "reasoning": "Spec states SEER 18, exceeding requirement of 16.",
      "requirementSource": {"source_document": "...", "source_page": 3, "section_id": "s2"},
      "evidence": [{"source_document": "...", "page_number": 12, "excerpt": "SEER rating: 18", "vendor": "Carrier"}],
      "gaps": []
    }
  ]
}
```

---

## Modal Execution

### App Configuration

- **App name**: `fluiddoc-nexus`
- **Image**: Debian slim + Python 3.11 + Node.js 20 + `@anthropic-ai/claude-code@latest`
- **Timeout**: 30 minutes
- **Endpoints**: 2 (health + validate) — constrained by Modal free-tier limit of 8 web endpoints

### Authentication

The Claude Agent SDK authenticates via `CLAUDE_CODE_OAUTH_TOKEN` — a long-lived token generated by `claude setup-token` (requires Claude Max subscription). This is stored in the `fluiddoc-claude-max` Modal secret.

**Additional container setup** (in image build):
- `~/.claude.json` created with `hasCompletedOnboarding: true` + `oauthAccount` info to skip the interactive setup wizard
- `useradd agent` for non-root execution paths
- `CI=true` environment variable

### Event Batching

To avoid exhausting EV's database connection pool (QueuePool limit: 10 + 20 overflow), events are buffered:

- **Buffer**: Accumulates raw SDK events in memory
- **Flush interval**: Every 3 seconds
- **Flush threshold**: 30 events max per batch
- **Force flush**: On orchestrator completion (before sending the completion callback)
- **Result**: ~20 DB rows for ~100+ raw events (vs 100+ individual writes without batching)

### Three-Phase Architecture

1. **Phase 1 — Requirements Extraction** (~2-5 min): One Claude Sonnet SDK client scans the requirements project via KG tools, extracts all testable requirements as structured JSON
2. **Phase 2 — Parallel Validation** (~3-10 min): N concurrent SDK clients (one per requirement), each validates against the specs project using `graph_search` and `kg_get_section`
3. **Phase 3 — Report Compilation** (instant): Python aggregation of results into ComplianceReport

---

## Frontend Integration

### Flow (Live Mode)

1. User selects specs + requirements projects on `/submittal-reviews` page
2. Clicks "Run Comparison" → navigates to `/submittal-reviews/compare?specs={id}&requirements={id}`
3. `useNexusStream.startStream()`:
   - Creates `SubmittalReview` in EV via POST
   - Dispatches to Modal (fire-and-forget, no await)
   - Starts polling EV every 5 seconds
4. Polling loop:
   - Fetches review status + new events (incremental offset)
   - Unpacks `eventMetadata.batch[]` arrays
   - Feeds raw SDK events through `nexus-stream-parser.ts`
   - Renders tool calls, thinking blocks, compliance results in activity feed
5. On terminal status: stops polling, fetches line items, shows report

### Flow (Hydration/Refresh)

When URL has `review_id` param:
1. `hydrateFromReviewId()` fetches all historical events from EV
2. Replays them through the parser (same as live mode)
3. If review is still `running`: resumes polling
4. If `completed`: shows report immediately

### URL Parameters

| Param | Purpose |
|-------|---------|
| `specs` | Specs project UUID |
| `requirements` | Requirements project UUID |
| `review_id` | EV review UUID (for hydration) |
| `run_id` | FluidDoc run UUID (legacy hydration) |
| `max_req` | Max requirements to validate |
| `tab` | Active tab: `activity` (default) or `report` |

### Priority: `review_id` > `run_id` > `specs+requirements`

---

## Authentication & Secrets

### Modal Secrets

| Secret | Keys | Purpose |
|--------|------|---------|
| `fluiddoc-claude-max` | `CLAUDE_CODE_OAUTH_TOKEN` | Claude Max subscription auth for Agent SDK |
| `fluiddoc-neo4j` | `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Knowledge Graph |
| `fluiddoc-mongodb` | `MONGODB_URI`, `DATABASE_NAME` | Document content store |
| `fluiddoc-gemini` | `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_EXTRACTION_MODEL` | VLM fallback |
| `fluiddoc-aws` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` | S3 page images |
| `fluiddoc-github` | `GITHUB_TOKEN` | Install fz-contracts from private repo |

### Token Generation

```bash
# Generate long-lived OAuth token (valid ~1 year)
claude setup-token

# Token format: sk-ant-oat01-...
# Store in Modal:
modal secret create fluiddoc-claude-max CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-...
```

### Callback URL

The Modal dispatch route sets `callback_base_url` to the ngrok/staging URL. Modal constructs the full callback as: `{callback_base_url}/api/submittal-reviews/{review_id}/status`

**Current (dev)**: ngrok URL in `dispatch/route.ts`
**Production**: `https://api.fluidzero.ai` or from `API_URL` env var

---

## Event Pipeline

### Raw Event Types (from Claude Agent SDK)

Every event emitted by `serialize_message()` in the Nexus orchestrator is stored as-is:

| Event Type | Content | Size Range |
|-----------|---------|-----------|
| `session_start` | run_id, project IDs, model, architecture | ~300 bytes |
| `phase_start` | phase name, timestamp | ~100 bytes |
| `SystemMessage` | Full SDK init (tools, MCP servers, model, version, permissions) | ~2 KB |
| `AssistantMessage` | ThinkingBlock, ToolUseBlock, TextBlock content | 300 bytes - 3 KB |
| `UserMessage` | ToolResultBlock responses (raw KG data) | 1 KB - 40 KB |
| `nexus_tool_call` | Tool name, tool_use_id, elapsed, timestamp | ~230 bytes |
| `tool_call` | Generic tool calls (ToolSearch, Bash) | ~180 bytes |
| `RateLimitEvent` | Rate limit info from Anthropic API | ~550 bytes |
| `ResultMessage` | Session summary, usage stats, cost | ~500 bytes |
| `requirements_extracted` | Count + requirement IDs | varies |
| `compliance_result` | Full ComplianceLineItem with evidence | varies |

### Storage Format

Events are batched in `submittal_review_events.event_metadata`:

```json
{
  "batch": [
    {"type": "AssistantMessage", "content": [...], "model": "...", ...},
    {"type": "UserMessage", "content": [...], ...},
    {"type": "nexus_tool_call", "tool_name": "mcp__nexus__graph_search", ...}
  ],
  "count": 3
}
```

### Zero Modification Guarantee

The chain from SDK to DB:
1. `serialize_message(msg)` → dict (JSON-safe via `_make_json_safe`)
2. `on_event(entry)` → `_event_buffer.append(event)` — **no modification**
3. `_flush_buffer()` → wraps as `{"batch": [...], "count": N}` — **events untouched**
4. `_post_status()` → `json.dumps(payload, default=str)` — **events unchanged**
5. EV stores `event_metadata` as JSONB — **PostgreSQL stores as-is**

---

## Files Changed

### Escape Velocity (`escape-velocity/`)

| File | Change | Lines |
|------|--------|-------|
| `src/models/submittal_review.py` | **NEW** — SubmittalReview model + SubmittalReviewStatus enum | ~160 |
| `src/models/submittal_review_line_item.py` | **NEW** — SubmittalReviewLineItem model | ~70 |
| `src/models/submittal_review_event.py` | **NEW** — SubmittalReviewEvent model (immutable) | ~65 |
| `src/schemas/submittal_review.py` | **NEW** — Pydantic request/response schemas | ~170 |
| `src/api/routers/submittal_reviews.py` | **NEW** — API router (8 endpoints) | ~350 |
| `src/models/__init__.py` | Modified — register new models | +6 |
| `src/schemas/__init__.py` | Modified — export new schemas | +12 |
| `src/api/main.py` | Modified — mount new router | +2 |
| `src/models/project.py` | Modified — add submittal_review_count + relationship | +5 |
| `src/models/run.py` | Modified — add NEXUS to PipelineMode enum | +1 |
| `migrations/versions/a2a3192a146f_*.py` | **NEW** — add nexus to pipeline_mode enum | auto |
| `migrations/versions/894f4748d036_*.py` | **NEW** — add submittal review tables | auto |

### FluidDoc (`fluiddoc/`)

| File | Change | Lines |
|------|--------|-------|
| `fluiddoc/modal/nexus_sandbox.py` | **NEW** — Modal app with validate + health endpoints | ~270 |
| `fluiddoc/modal/nexus_schemas.py` | **NEW** — NexusModalRequest schema | ~25 |
| `fluiddoc/core/config.py` | Modified — add modal_nexus_* settings | +4 |
| `fluiddoc/worker/sqs_worker.py` | Modified — add _dispatch_nexus_to_modal() | +120 |
| `fluiddoc/agents/nexus/agent_config.py` | Modified — change permission_mode to acceptEdits | ~3 |

### Fennec UI (`fennec-ui/`)

| File | Change | Lines |
|------|--------|-------|
| `lib/api/types.ts` | Modified — add SubmittalReview types | +80 |
| `lib/api/server.ts` | Modified — add server API functions | +45 |
| `lib/hooks/use-nexus-stream.ts` | **Major rewrite** — SSE → EV polling + dispatch + hydration | ~600 |
| `app/api/backend/submittal-reviews/route.ts` | **NEW** — org-wide list proxy | ~35 |
| `app/api/backend/submittal-reviews/[reviewId]/route.ts` | **NEW** — GET detail proxy | ~22 |
| `app/api/backend/submittal-reviews/[reviewId]/status/route.ts` | **NEW** — POST callback proxy | ~35 |
| `app/api/backend/submittal-reviews/[reviewId]/line-items/route.ts` | **NEW** — GET results proxy | ~28 |
| `app/api/backend/submittal-reviews/[reviewId]/events/route.ts` | **NEW** — GET audit trail proxy | ~50 |
| `app/api/backend/submittal-reviews/[reviewId]/cancel/route.ts` | **NEW** — POST cancel proxy | ~22 |
| `app/api/backend/submittal-reviews/[reviewId]/dispatch/route.ts` | **NEW** — POST Modal trigger | ~55 |
| `app/api/backend/projects/[projectId]/submittal-reviews/route.ts` | **NEW** — POST/GET proxy | ~45 |
| `app/(app)/[orgId]/submittal-reviews/page.tsx` | Modified — add past reviews listing | +100 |
| `app/(app)/[orgId]/submittal-reviews/compare/page.tsx` | Modified — Suspense wrapper | +5 |
| `app/sandbox/compare/page.tsx` | Modified — review_id priority, tab URL param | +10 |

---

## Database Migrations

Two migrations applied to staging:

### 1. `a2a3192a146f` — Add nexus to pipeline_mode enum
```sql
ALTER TYPE pipeline_mode ADD VALUE IF NOT EXISTS 'nexus';
```

### 2. `894f4748d036` — Add submittal review tables
- Creates `submittal_reviews` table with all columns + 5 indexes
- Creates `submittal_review_events` table with unique constraint on (review_id, sequence_number)
- Creates `submittal_review_line_items` table with unique constraint on (review_id, sequence_number)
- Adds `submittal_review_count` column to `projects` (default 0)
- Creates `submittal_review_status` PostgreSQL enum

---

## Deployment Checklist

### Modal
- [x] Deploy nexus sandbox: `uv run modal deploy fluiddoc/modal/nexus_sandbox.py`
- [x] Create secrets: `fluiddoc-claude-max`, `fluiddoc-neo4j`
- [x] Update existing secrets: `fluiddoc-mongodb` (add DATABASE_NAME), `fluiddoc-gemini` (add model configs)
- [x] Verify health: `curl https://fluidzero--fluiddoc-nexus-nexusendpoint-health.modal.run`

### Escape Velocity
- [x] Apply migrations: `alembic upgrade head`
- [x] Deploy new router (included in next ECS deploy)
- [ ] Set `CALLBACK_URL` for production (currently ngrok for dev)

### FluidDoc
- [x] Set `MODAL_NEXUS_ENABLED=true` in staging env
- [x] Set `MODAL_NEXUS_ENDPOINT_URL=https://fluidzero--fluiddoc-nexus-nexusendpoint-validate.modal.run`
- [ ] Deploy to ECS (included in next deploy)

### Fennec UI
- [ ] Deploy to Vercel (included in next deploy)
- [ ] Update dispatch route callback URL from ngrok to production EV URL

---

## Known Limitations

1. **0-requirement completions**: The Nexus agent sometimes fails to extract requirements from the KG, resulting in a completed review with 0 line items. This is an agent/prompt issue, not infrastructure.

2. **Modal free-tier endpoint limit**: Only 2 endpoints deployed (health + validate). The SSE streaming endpoint (`validate_stream`) was removed to stay within the 8-endpoint limit. Can be re-added after plan upgrade.

3. **Callback URL hardcoded**: The dispatch route currently uses an ngrok URL for dev. Production requires setting the correct EV URL.

4. **No webhook delivery**: Submittal reviews don't trigger webhook delivery (unlike extraction runs). Can be added if needed.

5. **No document snapshotting**: Unlike extraction runs, submittal reviews don't create document snapshots. The review references projects by ID; document state is not frozen at review creation time.

6. **No SQS integration**: The SQS worker dispatch code for nexus (`_dispatch_nexus_to_modal`) is written but not yet used in production. Currently, the frontend dispatches directly to Modal via the dispatch proxy route.

7. **Agent runs as root on Modal**: The `permission_mode` was changed from `bypassPermissions` to `acceptEdits` because `--dangerously-skip-permissions` is blocked for root users. This means the agent cannot write files or run arbitrary commands, only use allowed tools.
