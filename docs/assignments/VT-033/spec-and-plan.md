# VT-033 - Specification and plan before implementation

Author: Mai Huy Hoàng (23001878), SE2026-T09, AI-01. AI assistance: Codex.
Baseline: `9ee864c3404f8057b394592791404f6db8692826`.
Module owner: Notification (TV4); shared Settings requires Common/Identity owner review.
This document is created before production changes. Student review is pending.

## Problem statement

Notification currently inherits a hardcoded default of 20 from shared pagination.
An operator should be able to change the Notification default in one process setting
without editing call sites or changing pagination for Classroom, Identity, Social or
Administration. This is an implementation configuration of an existing API, not a
new business permission or endpoint.

## Acceptance criteria

1. **AC1**: Without the new environment setting, an omitted `limit` returns the newest
   20 own notifications (or all if fewer). `NOTIFICATION_PAGE_SIZE_DEFAULT` accepts
   integers 1..100, loaded when Settings/process initializes; an omitted limit uses
   that configured default, including 1, 2 and 100. Invalid configuration fails
   Settings validation; no silent fallback or runtime reload is promised.
2. **AC2**: Explicit `limit=1..100` overrides the configured default. BVA inputs
   0 and 101 are rejected with the existing validation envelope; invalid or foreign
   cursors remain rejected. No data is written by a list request.
3. **AC3**: The business response keeps `{items,unread_count,next_cursor}`,
   sequence DESC ordering, exact expected IDs, correct cursor continuation, unread
   count across the whole inbox and `Cache-Control: no-store`.
4. **AC4**: Current Identity authentication and recipient isolation are retained:
   User A cannot list or mark read User B's notification under any page default;
   B's `read_at` remains unchanged after the denied mutation. Locked/revoked users
   remain rejected. Read-all and repeated mark-read retain their baseline semantics.
5. **AC5**: Other pagination users still default to 20; no schema, migration,
   dependency, permission or framework change. Existing Core regression tests run
   on the dedicated local PostgreSQL test server, with skips reported separately.

## Non-functional constraints

- Small production patch: existing pydantic-settings and cursor helper; keep shared
  `get_pagination` unchanged. Tests/harness/docs can be larger than the feature.
- Exercise 120 simultaneous closed-loop tasks over actual loopback HTTP and
  PostgreSQL 16. Client p95 target <=3500 ms, content/ownership validation and error
  counts are mandatory. Report a failed result or environment limit honestly.
- Never log tokens, credentials or private data; use synthetic users and a generated
  sibling database. No operational database migrations or destructive cleanup.

## Invariant and conditions

Invariant: User A never reads or marks read a notification belonging to User B,
regardless of pagination configuration.
Preconditions: validated Settings; authenticated ACTIVE current user; DB and current
Identity lookup available; query validation succeeds; cursor belongs to own inbox.
Postconditions: list IDs are a descending, nonduplicated own-inbox slice; unread count
is for the whole own inbox; no read state changes. A cross-recipient mark-read leaves
all B rows unchanged and returns 404. A failed transaction rolls back.

## Initial AI candidates (actual proposals, before review)

- **P1**: Add a configurable default parameter to the shared `get_pagination` helper
  and reuse it from Notification to avoid duplicating query/cursor validation.
- **P2**: Resolve the setting during each request so tests can switch environment
  variables without restarting/importing the application.
- **P3**: Start with a mocked NotificationService API test to demonstrate the resolved
  default, then add real PostgreSQL outcome tests and the authorization mutation.
- **P4**: Reuse `class_list_load.py` directly, increasing its maximum actor count.

These are candidates, not accepted implementation decisions. A separate repository
review must correct/reject unsuitable candidates before production code is changed.

## Proposed sequence and files

1. Capture host, Git and dependency inventory. Keep the existing assignment branch
   and untracked user's master prompt. Do not fetch/rebase to alter the baseline.
2. Audit Business Rules, Core design/API/folders, source and existing tests; save an
   independent read-only review of this plan before production changes.
3. Run baseline lint, format, Notification contract/PostgreSQL and full Core tests.
4. Add `tests/notification/test_vt033_config.py` and PostgreSQL tests. Obtain real RED
   on unchanged production code (asserting configured default, not import/DB errors).
   Commit RED tests and plan separately.
5. Add one bounded Settings field and a Notification-owned pagination dependency in
   `app/modules/notification/router.py`. Update Core README/API contract for the
   config. Review diff and run GREEN/real DB/full regressions; commit correct patch.
6. After correct patch is committed, remove only the recipient predicate from
   `NotificationRepository.mark_read` locally, capture exact diff, run the same
   security test, restore exact original bytes in `finally`, rerun security tests.
   Do not commit or push mutated production source.
7. Add standalone `tests/performance/vt033_notification_load.py`, with 120 actors,
   synchronized start, own synthetic inboxes and actual Uvicorn/Identity/DB. Measure
   a smoke and a sustained run with warmup. Keep original class harness unchanged.
8. Record line/branch and risk coverage, two repeat/reorder flaky experiments,
   traceability, AI usage, a 250..350-word Vietnamese reflection and reproduction.
9. Commit related groups, push assignment branch, create Draft PR to main, inspect
   actual CI and PR state. Never merge. Export/inspect PDF after real URLs exist.

Rollback: revert only the feature commits after review; no schema rollback required.
Mutation restoration uses exact saved bytes and verifies source hash. Test cleanup
drops only generated databases and never removes existing Docker volumes.

## Risks / human review

Review required from Notification owner and Common/Identity consumers for shared
Settings, OpenAPI optional limit documentation and config deployment. Student must
read the report, reflection, mutation evidence and responsibility statement before
submission. No human-approved label is asserted. Existing broader Core failures,
dependency drift, background Docker activity and short local load duration must be
reported distinctly from feature failures and production capacity.
