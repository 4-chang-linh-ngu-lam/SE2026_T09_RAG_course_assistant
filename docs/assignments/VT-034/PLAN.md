# VT-034 — Spec → Test → Change → Verify → Review

Student: Bùi Văn Khởi, 23001893, SE2026-T09. Individual change; awaiting team review.
Baseline: `9ee864c3404f8057b394592791404f6db8692826`.
Branch: `bt3/23001893-vt034-notification`.

## Specification (before implementation)

Problem: classmates can miss an author's correction to a class post. Add an in-app
notification for a successful, content-changing post update without coupling the
committed post to subsequent notification delivery availability.

- AC1: an authorized author changing a post enqueues exactly one
  `SOCIAL_POST_UPDATED` event in the same transaction; identical content is a no-op.
- AC2: delivery failure after commit leaves the edited post intact, marks the
  event for retry, and a successful retry creates one inbox item per eligible
  recipient; replay must not duplicate that event's inbox items.
- AC3: revoked/cross-school recipients, the author and deleted sources do not
  receive a notification. Original write permissions remain enforced.
- AC4: accept nonblank body lengths 1..10000; reject blank/10001 before writing.
  Events/inbox contain IDs only, never the body. Producer does not fan out inline.
- AC5: worker batch_size must be an integer in 1..1000, validated before opening
  DB sessions. Bound oversized calls; accept exactly 1000 (mutation target).

NFC1: measure client-side p95 <=2.0 seconds for 60 concurrent HTTP update tasks,
with 10000-character synthetic input; distinguish a local harness from production.
NFC2: no raw content/credentials in event, inbox or error log; preserve current
permissions and public API schema. No migration, broker or new service.

Invariant: business mutation and durable event intent commit atomically. Delivery
is a separate transaction after commit. Failure to enqueue MUST roll back the edit;
failure to deliver MUST NOT roll back that committed edit.

Assumptions: all other current eligible class members should be notified; identical
body sends no event; no text diff in the inbox. These choices implement this CR on
an unmerged individual branch and need TV3/TV4 acceptance, not a new global rule.

## Coding-agent prompt / initial plan

Prompt P1 (task distilled from the user's VT-034 instructions):
"Plan before coding. Add in-app notifications for a changed class post. Protect
the primary transaction, test oversized inputs, use pairwise data, test first,
mutate > to >=, and measure 60 concurrent operations with p95 <=2s. Propose files,
assumptions and a small slice using the actual Core repository."

Initial AI plan output: (1) call the notification sender from update_post and catch
all failures so updates always succeed; (2) add a broker/new notification table;
(3) test only HTTP 200 for a short and a 10000-character update; (4) validate batch
size in the CLI; (5) add a new event and a Vietnamese UI label.

## Repository review before code

R1 REJECT (1): common/outbox.py and notification/public.py explicitly require
atomic enqueue. notification/worker.py already isolates delivery with retry.
Use record_outbox_event + snapshot_audience, never swallow enqueue failures.

R2 REJECT (2): ADR-001 fixes five services; OutboxEvent, Notification and their
dedup/retry repository already exist. Reuse them; do not add broker/schema.

R3 REVISE (3): HTTP status alone cannot prove durable event, content integrity or
dedup. Assert persisted edit, event payload, recipient IDs, retry state, inbox count.

R4 REVISE (4): main() validates CLI but drain_outbox() can be called directly by
background_worker. Validate at function entry and test no DB access on bad values.

Revised planned production files: social/feed/service.py; notification/events.py;
notification/worker.py; apps/web/src/lib/data/live-core.ts. Update Core API contract
for event semantics, without changing OpenAPI request/response schemas.
Tests/harness/evidence: services/core/tests/vt034/** and this documentation folder.

## AI-generated weak tests reviewed

Draft W1 (removed from executable suite):
`assert client.patch(url, json={"body": "changed"}).status_code == 200`.
Weak: could pass without any notification. Replace with durable post + outbox checks.

Draft W2 (removed; redundant with W1's oracle):
`assert client.patch(url, json={"body": "x" * 10000}).status_code == 200`.
Weak: adds length variation but no independent invariant. Replace with explicit
max/max+1 validation plus payload-size/privacy and failure/retry tests.

The drafts are preserved here as review evidence and deliberately not collected.
The coding agent performed this review; the student must independently inspect
the final diff, test data and reflection before adopting/submitting the work.
