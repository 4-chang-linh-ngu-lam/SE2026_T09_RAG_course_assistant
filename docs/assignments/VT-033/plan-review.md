# Independent read-only plan review

Reviewer: separate Codex agent `vt033_plan_review`, explicitly requested by the user.
Review completed before production changes, against baseline
`9ee864c3404f8057b394592791404f6db8692826`. Reviewer changed no files, Git state or
databases and executed no tests. This is AI review, not student/owner approval.

Decision: proceed with the following corrections to the actual initial proposals
recorded in `spec-and-plan.md`.

| Candidate | Decision | Repository evidence and correction |
|---|---|---|
| P1 shared configurable pagination | Corrected | `common/pagination.py:39-40` defaults to20. Consumers: Classroom `router.py:248`, Identity `router.py:355`, Administration `router.py:46`, Feed `router.py:41`, Comments `router.py:38`, Calendar `router.py:39`. Keep shared function unchanged; resolve default in Notification dependency and call helper with explicit args. |
| P2 environment resolution per request | Rejected | `common/config.py:8,46,76` already defines Settings, environment config and process singleton. Add `Field(default=20,ge=1,le=100)`. Read loaded field; never read env/construct Settings on each request. Validate initialization in fresh Settings/subprocess tests. |
| P3 mocked route RED | Accepted narrowly, strengthened | Existing `tests/notification/test_contract.py:47` mocks service and checks Pagination. It proves parameter routing only. Add actual PostgreSQL exact IDs/order/cursor/count and persisted `read_at`; mutation test should check B's state before HTTP status. |
| P4 raise max on class-list harness | Rejected | `tests/performance/class_list_load.py:128,175` constructs/caps100 actors; `145-152` exercises classes, `332-335` gates backend500ms. New Notification harness must gate client3500ms and support actual120 independent actors. |

All abbreviated production paths above are relative to `services/core/app/`.
Line references describe the unchanged baseline, not later shifted line numbers.

## Final implementation recommendation

One bounded Settings field; Notification-local dependency with optional limit,
existing bounds/cursor length. Use `limit is None`, preserve explicit valid limits,
and call existing cursor helper. No changes to service/repository/auth/schema or
migrations. Update Core README and API Contract default paragraph at line102.

## Business rules / owners

No conflict found: Business Rules G4 (line67) establishes notifications; API Contract
lines92,102-103 already require own inbox, 1..100, descending sequence, whole-inbox
unread count, current Identity, no-store and first-read timestamp. Design line105
requires recipient locking. User's change authorizes extending deployment config,
not changing recipient policy. Notification TV4 and Common/Identity owner review
remains pending (`docs/CONTRIBUTING.md:15` and shared-file review rules).

## Review warnings adopted

- RED must be the configured2-versus-baseline20 assertion, not missing attribute,
  import error, inaccessible DB or fixture error.
- BVA both configuration and query: 0,1,2,99,100,101. Seed >100 own rows plus other
  user's data; a 3-row default100 test is insufficient.
- Use generated sibling databases; fixture reuse must not duplicate old tests.
- Mutation must execute real repository guard `repository.py:62`; save exact bytes,
  restore in `finally`, verify hash and rerun. Never push mutant.
- Load must run actual app/Identity with synthetic JWTs, no auth/service override.
  Track barrier, task count and peak client in-flight. Backend admission deliberately
  limits execution (`common/admission.py:23-43`); 120 actors is not 120 DB operations.
- Separate warmup and measurement; aggregate client p50/p95/p99/max, backend latency,
  errors/content mismatches/timeouts. Fast 503s must not produce a load PASS.
- Repeats/reorders with restored settings/overrides and controlled concurrency are
  finite experiments, not proof that tests can never flake.

Human review pending: student report/reflection/responsibility statement, shared
configuration, Notification and affected module owners.
