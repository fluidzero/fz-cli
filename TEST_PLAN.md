# FluidZero CLI Test Plan

End-to-end tests against local backend (http://localhost:8000).

## Prerequisites
- [x] Backend running (`curl localhost:8000/health`)
- [x] Authenticated (`fz auth status` shows valid token)
- [ ] Test PDF file created

## Test Matrix

### Phase 1: Auth
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 1.1 | `fz auth status` | Shows user, org, role, token expiry | |
| 1.2 | `fz auth token` | Prints JWT to stdout | |
| 1.3 | `fz auth token \| wc -c` | Non-empty output | |

### Phase 2: Projects CRUD
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 2.1 | `fz projects list` | Table with existing projects | |
| 2.2 | `fz projects list --json` | JSON array | |
| 2.3 | `fz projects create "CLI Test" --description "test"` | 201, returns project ID | |
| 2.4 | `fz projects get <id>` | Shows project details | |
| 2.5 | `fz projects update <id> --name "CLI Test Updated"` | Updated name | |
| 2.6 | `fz projects list -o csv` | CSV output | |
| 2.7 | `fz projects list -o jsonl` | JSONL output | |

### Phase 3: Documents
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 3.1 | `fz documents upload -p <id> test.pdf` | Upload + progress | |
| 3.2 | `fz documents list -p <id>` | Shows uploaded doc | |
| 3.3 | `fz documents get <doc-id>` | Document details | |
| 3.4 | `fz documents list -p <id> --status ready` | Filtered list | |

### Phase 4: Schemas + Versions
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 4.1 | `fz schemas create -p <id> "Test Schema" --schema '{...}'` | 201 | |
| 4.2 | `fz schemas list -p <id>` | Shows schema | |
| 4.3 | `fz schemas get <schema-id>` | Schema details | |
| 4.4 | `fz schemas versions list <schema-id>` | v1 | |
| 4.5 | `fz schemas versions create <schema-id> --schema '{...}' --message "v2"` | v2 created | |
| 4.6 | `fz schemas versions list <schema-id>` | v1 + v2 | |
| 4.7 | `fz schemas versions get <schema-id> --version 1` | v1 details | |
| 4.8 | `fz schemas versions diff <schema-id> --from 1 --to 2` | Shows diff | |
| 4.9 | `fz schemas update <schema-id> --name "Renamed"` | Updated | |

### Phase 5: Prompts + Versions
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 5.1 | `fz prompts create -p <id> "Test Prompt" --text "Extract..."` | 201 | |
| 5.2 | `fz prompts list -p <id>` | Shows prompt | |
| 5.3 | `fz prompts get <prompt-id>` | Prompt details | |
| 5.4 | `fz prompts versions list <prompt-id>` | v1 | |
| 5.5 | `fz prompts versions get <prompt-id> --version 1 --text-only` | Raw text | |

### Phase 6: Runs
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 6.1 | `fz runs create -p <id> --schema <sid>` | Run created | |
| 6.2 | `fz runs list -p <id>` | Shows run | |
| 6.3 | `fz runs get <run-id>` | Run details | |
| 6.4 | `fz runs documents <run-id>` | Doc snapshots | |
| 6.5 | `fz runs events <run-id>` | Status events | |
| 6.6 | `fz runs results <run-id>` | Results (may be empty) | |

### Phase 7: Search
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 7.1 | `fz search "test" -p <id>` | Search results or empty | |
| 7.2 | `fz search "test" -p <id> --json` | JSON output | |

### Phase 8: Webhooks
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 8.1 | `fz webhooks create -p <id> --name "Test" --url https://httpbin.org/post --event run.completed` | 201 | |
| 8.2 | `fz webhooks list -p <id>` | Shows webhook | |
| 8.3 | `fz webhooks get <wh-id>` | Webhook details | |
| 8.4 | `fz webhooks test <wh-id>` | Test delivery | |
| 8.5 | `fz webhooks deliveries <wh-id>` | Delivery logs | |
| 8.6 | `fz webhooks update <wh-id> --name "Updated"` | Updated | |

### Phase 9: Output Formats (cross-cutting)
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 9.1 | `fz projects list -o json` | Valid JSON | |
| 9.2 | `fz projects list -o jsonl` | One JSON per line | |
| 9.3 | `fz projects list -o csv` | CSV with headers | |
| 9.4 | `fz projects list -q` | No output | |

### Phase 10: Error Handling
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 10.1 | `fz projects get 00000000-0000-0000-0000-000000000000` | 404 + hint | |
| 10.2 | `fz schemas list` (no -p) | Usage error | |
| 10.3 | `fz runs create` (no --schema) | Usage error | |

### Phase 11: Cleanup
| # | Command | Expected | Status |
|---|---------|----------|--------|
| 11.1 | `fz webhooks delete <wh-id> --confirm` | 204 | |
| 11.2 | `fz schemas delete <schema-id> --confirm` | 204 | |
| 11.3 | `fz projects delete <id> --confirm` | 204 | |
