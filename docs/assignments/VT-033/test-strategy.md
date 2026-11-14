# Risk-based strategy / planned traceability

Highest risk R1: a status-only assertion can miss another user's rows or incorrect
pagination. R2: shared default regression. R3: invalid configuration silently used.
R4: transaction/read state corruption. R5: local load mistaken for capacity proof.
Rule anchors: G4 in-app notifications, K2 current account status, K5 safe logs;
recipient-only behavior is already specified by Core API Contract, not invented here.

Unit tests verify Settings BVA and environment parsing/startup. API contract tests
verify dependency resolution with exact expected objects. PostgreSQL API tests use
actual Identity lookup, NotificationService/repository and committed synthetic rows;
they assert ordered IDs, cursor, count and persisted `read_at`. Real loopback HTTP
load tests the actual app and Identity dependency, with no authorization override.
Existing Core HTTP journey tests cover the wider workflow. A new browser E2E would
add little value for an environment-only backend default; UI/RAG is outside scope.

| ID | Risk/AC | Level | Preconditions/Input | Expected business outcome | Priority | Test file/function |
|---|---|---|---|---|---|---|
| T01 | R3/AC1 | Unit | Env absent | Settings default exactly 20 | P1 | test_vt033_config.py::test_settings_default |
| T02 | R3/AC1 | Unit BVA | Config 0,101 | ValidationError, no fallback | P1 | test_vt033_config.py::test_settings_boundaries |
| T03 | R3/AC1 | Unit BVA | Config 1,2,99,100 | Exact parsed int preserved | P1 | test_vt033_config.py::test_settings_boundaries |
| T04 | R3/AC1 | Process | Env invalid/noninteger | Import Settings exits nonzero before startup | P1 | test_vt033_config.py::test_invalid_env_prevents_startup |
| T05 | R1/AC1 | API | New default 1,2,100 | Service receives configured limit with actor ID | P1 | test_vt033_config.py::test_route_resolves_default |
| T06 | R1/AC2 | API BVA | Query 1,2,99,100; default 2 | Exact explicit limit passed; no-store | P1 | test_vt033_config.py::test_explicit_limit_overrides_default |
| T07 | R1/AC2 | API negative | Query 0,101,noninteger | 422 error envelope, service not called | P1 | test_vt033_config.py::test_invalid_query_never_calls_service |
| T08 | R2/AC5 | API regression | Classroom list omits limit, Notification default 2 | Classroom still receives limit20 | P1 | test_vt033_config.py::test_other_endpoint_keeps_twenty |
| T09 | R1/AC1,3 | PG API | Default 1,2,100; 103 own/3 other rows | Exact own descending IDs, payloads, read flags, count102, valid continuation | P1 | test_vt033_postgres.py::test_configured_inbox_business_outcome |
| T10 | R1/AC2,3 | PG API BVA | Explicit 1,2,99,100; default2 | Exact own page size and IDs, cursor, unread count | P1 | test_vt033_postgres.py::test_explicit_limit_business_outcome |
| T11 | R1/AC2,4 | PG API negative | Foreign cursor | 400, own and other read state unchanged | P1 | test_vt033_postgres.py::test_foreign_cursor_does_not_change_state |
| T12 | R1,R4/AC4 | PG API security | A marks B's unread notification | B.read_at stays None; own inbox unchanged; 404 | P0 | test_vt033_postgres.py::test_cross_recipient_mark_read_preserves_business_state |
| T13 | R4/AC4 | PG API | Own mark twice then read-all | First read_at preserved; own unread0; B unread3 | P1 | test_vt033_postgres.py::test_own_read_and_read_all_preserve_other_inbox |
| T14 | R1/AC4 | PG API negative | Lock actor after token creation | 401 and unchanged persisted rows | P0 | test_vt033_postgres.py::test_locked_user_cannot_read_inbox |
| T15 | R4/AC3 | PG failure path | Inject unread-count DB operation failure | 500 safe envelope; transaction exits cleanly; next real list succeeds and data unchanged | P1 | test_vt033_postgres.py::test_list_failure_rolls_back_and_recovers |
| T16 | R1/AC1,3 | PG API regression | Default20 env absent; empty inbox | 20 own rows normally; empty other actor returns [],0,None | P1 | test_vt033_postgres.py::test_baseline_default_and_empty_inbox |
| T17 | R1/AC2 | API negative | malformed/too-long cursor | Existing 400/422; no call/write | P2 | test_vt033_config.py::test_invalid_query_never_calls_service |
| T18 | R5/NFR | Loopback HTTP + PG | 120 distinct actors, simultaneous barrier, 30s warmup + sustained measurement | Exact own IDs/read/count/cursor; max in-flight120 recorded; client p95<=3500ms, errors0 | P1 | performance/vt033_notification_load.py |

Negative cases T02/T04/T07/T11/T12/T14/T17; failure path T15. Each parametrized
boundary is an executed test instance, not an invented pass. Traceability will be
updated with actual commit SHA and evidence after execution.

Flaky experiments: (F1) repeat selected config/PG tests in reverse file/test order,
fresh fixture databases each run; (F2) repeat the security/cursor/read tests and
existing controlled read-all/delivery concurrency test, with explicit synchronization
and exact timestamp comparison rather than wall-clock sleeps. Load has a barrier,
fixed seeded ordering and aggregate run metadata; no random ordering assertion.
Finite repeats do not prove absence of flakes.
