# Core backend verification — TASK-015

Scope: backend only, per user direction on 2026-10-19. This suite exercises real
PostgreSQL 16 transactions, HTTP routes and public permission interfaces. It does
not implement or certify Web journeys. Document/AI/Learning/Learner Intelligence
scenarios remain pending until those services have approved implementations.

## Run and retain evidence

From `services/core`, install `.[dev]` and set `TEST_DATABASE_URL` to a disposable
PostgreSQL 16 server/account with CREATEDB. The integration fixtures create/drop
their own databases; older Identity/Classroom fixtures also use transactions in
the specified test database. Never point this variable at an operational server.

```sh
python -m pytest -q -W error -p no:cacheprovider --cov=app --cov-branch --cov-report=xml --junitxml=test-results.xml
python tests/security/evidence.py --junit test-results.xml --output rule-evidence.json
python -m pytest tests/identity/test_public.py -q -W error -p no:cacheprovider --cov=app.modules.identity.public --cov-branch --cov-fail-under=100
python -m ruff check app tests migrations
python -m ruff format --check app tests migrations
```

Without the test database, DB tests skip; that is not DB verification. The evidence
command rejects skipped or missing selected tests and any skipped test case in the
input report. It writes identifiers/counts/results, without copying failure text,
HTTP headers, activation codes, request bodies or tokens into the rule report.
`scenarios.json` is the machine-readable Rule ID → scenario → test catalog; actual
results are computed from JUnit. A pending service never becomes passed because
other tests are green. `complete_core_g2` remains false.

**Latest full-suite evidence (2026-10-30):** dedicated CKEY VPS, PostgreSQL 16.15,
Python 3.12.16; `pytest -q -W error --tb=short` reported **381 passed, 0 failed**.
Ruff check/format, migration upgrade to head, and `alembic check` also passed. This
was a working-tree test run, not GitHub CI or a staging/production migration.

## Traceability and limits

| Requirement | Backend evidence | Scope still pending |
|---|---|---|
| Core-01 / QAS-04 / A1–A8, F1–F5, H1, K2, L2, M2/M5 | `security/test_permissions.py`: current scope/status vs issued JWT, Admin-only mutations, obsolete self-join/leave absent, relation class/post/comment, identity lookup outage, replay cache scope; Classroom action tests for ended/archive/history | Document grants/raw sources, private AI chat; Learning own results/grading/appeals under M1/O4 |
| Core-02 / A1/A4/A7, F1/F2, H1/H2 | `security/test_concurrency.py`: 100 operations for each sync/transfer/import (300 total), 16 workers, real committed transactions; partial unique/history checks, MANUAL unaffected, durable import restart/replay; maintenance teacher assignment concurrency | Durable HTTP idempotency for non-import Classroom operations remains outside the approved current design |
| Core-03 / F1, K2/K4/K5 | Identity HTTP/service tests: Student no email, activation/purpose/expiry/reissue/recovery/legacy, cookie/CSRF, refresh replay/rotation, logout/password/status/role revocation, limiter and stale cache | Operator identity-verification/retention policy for real minors; these tests do not establish legal compliance |
| Core-04 / F4/F7, G1–G4, K4/K5, L1/L3 | `security/test_http_journey.py`: real HTTP login/provision/activate/enrollment/feed/comment/calendar/recipient notification/moderation/audit/transfer/archive/revoke; existing worker crash/retry/dedup/rollback; data-request types require explicit manual fulfillment attestation; DELETE remains deferred | Learning projection tests are Core contract/projection evidence only, not Learning E2E; ACCESS/EXPORT still rely on school-approved out-of-band fulfillment and CORRECTION on the owning service's audit |
| Core-04 boundaries | AST guard scans static absolute imports in production module files and literal cross-service SQL; own module imports and other modules' public interfaces are allowed | Static guard cannot prove absence of arbitrary dynamic imports or constructed SQL; real HTTP permission tests complement it |
| Core-05 | Migration/drift/legacy/roundtrip/seed, health and bounded request admission; backend-only clean Compose smoke, wheel/non-root, DB outage/recovery; CI JUnit/coverage/rule artifacts | Remote CI/reviewer approval requires an actual push/run; local green is not remote evidence |
| Core-06 / QAS-05 | Standalone `performance/class_list_load.py`, timed ASGI server plus separate client latency, scoped response validation and success ratio | Full mixed-service TP-01/RAG KPIs and end-user network performance are not certified |

Zero observed leaks in this finite synthetic suite is not a universal guarantee.
Fixtures are not production onboarding: first Admin/School use the guarded dev/test
seed, then actual business workflows. Load fixtures have unique unusable password
hashes; access JWTs exist only in memory for synthetic traffic, and actual backend
Identity/class permission lookup is still executed on every measured request.

## Core-02 concurrency semantics

Sync mixes 25 roster mutations with 75 sync calls; final explicit reconciliation
matches the committed roster, with historical membership episodes retained.
Transfer submits 100 identical requests under one process-local idempotency key;
one transfer/audit is committed. This does not assert that the key survives restart:
the current non-import cache is bounded/process-local. Import confirms one durable
preview 100 times, exactly one response discloses codes; a new app/cache reads the
same user IDs and null codes. Existing tests cover stale preview, CSV/XLSX and
owner-spanning rollback. No test restores legacy join requests or ownership transfer.

## Performance probe

Set `DATABASE_POOL_SIZE=15` and `DATABASE_MAX_OVERFLOW=0` for this measurement
profile (15 retained connections, not a larger maximum than the original 5+10).
The regular application defaults remain 5+10, and can be tuned explicitly via
environment. Then run:

```sh
python tests/performance/class_list_load.py --duration-seconds 600 --warmup-seconds 30 --users 100 --output core-load.json
python tests/security/evidence.py --junit test-results.xml --performance core-load.json --output rule-evidence.json
```

The runner creates/drops a `test_core_load_<UUID>` database, migrates to head,
creates 10 classes/500 synthetic Students (50/class) and uses 100 independent users.
It runs the actual Core app with one Uvicorn worker on loopback, default closed-loop
think interval 1 second, user starts evenly staggered within that interval, same
HTTP pool across warmup/measurement. It validates each returned class ID against
that user's enrollment. Count/rate may be below 100 requests/second if a client
waits for a response: this is a closed-loop user test, not a fixed arrival-rate test.

Backend p95 is measured around ASGI ingress → completion (includes admission and
response/dependency cleanup). Client p95 separately includes transport/client
waiting; do not substitute backend time for user-observed latency. All response
statuses count toward success, including overload/transport errors. The JSON has
CPU/RAM/OS/Python/PostgreSQL/pool/network, duration, counts, both p95 values and
source hashes, without DSN/credentials/headers. Short smoke runs are not Core-06
acceptance. Report `full_tp01_verified:false`: Document data/30-question assessments
and mixed-service traffic are unavailable. Shared local resource interference is
disclosed in the report; do not extrapolate this measurement to production capacity.

Core CI always runs backend tests/coverage/traceability. The optional
`workflow_dispatch → run_core_load=true` job repeats the 10-minute measurement on
PostgreSQL 16 and uploads its raw aggregate JSON. Remote runs are not implied by
the workflow file existing.

## Corrections discovered by this suite

- Classroom cached mutation replay used to check only current Admin role. After a
  scope change, it could disclose a prior school's class/roster/assignment response.
  Replay now rechecks source and destination resources, including empty 204 bodies,
  and the actual created course/homeroom/class for creation receipts. It returns 404
  on changed/missing scope. This is current-scope enforcement, not durable caching.
- Bursty requests could consume synchronous workers while waiting for pooled DB
  connections, yielding pool timeouts. The pure ASGI admission gate now waits before
  sync dependencies, bounds active API/internal requests by pool capacity (one slot
  reserved when possible), and holds its permit through dependency cleanup. Queue
  timeout uses `DATABASE_POOL_TIMEOUT_SECONDS`, returns safe no-store 503/Retry-After,
  and releases permits on exceptions/cancellation. Health/OpenAPI bypass the gate;
  liveness remains independent of the DB. Unit and real HTTP load verify this scope.

Changes to Common/Identity public/Classroom require owner review. No schema change,
new business endpoint, frontend implementation, deployment or provider change is
part of TASK-015 backend work.

Two delivery tests now explicitly backdate unattempted fixture events before a
single worker drain. These cases verify committed recipients/rollback/revocation,
not poll timing; tests for available_at/retry/backoff remain separate and unchanged.
Their failure diagnostics contain only event type/attempt count/database timestamps.
This avoids treating an event that is not yet due at the instant of a poll as a
recipient/atomicity failure. No production clock or worker schedule was changed.
