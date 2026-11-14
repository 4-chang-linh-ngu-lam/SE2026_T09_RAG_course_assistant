# AI Usage Log — VT-034

Tool: ChatGPT / Codex Work mode, current conversation, 14/11/2026 (Vietnam date).
No separate Claude/Gemini agent, external student work or prior member's test plan
was used. The coding agent wrote and reviewed the draft; final student review and
team review are still required. Do not describe this as an independently signed
student review.

## Input / prompts and output adopted

P0: the user's full VT-034 assignment, attached BT1/BT2 and official repository.
Exact key request: “thực hiện theo vòng lặp Spec → Test → AI-assisted Change →
Verify → Review”; “lỗi gửi thông báo không được làm hỏng giao dịch chính”;
“đổi toán tử so sánh biên > thành >=”; 60 concurrent tasks, p95 <=2.0s.

P1: the distilled implementation-plan prompt is recorded verbatim in PLAN.md,
committed before tests and patch. Output: initial candidate plan and reviewed
replacement using existing outbox/worker, no schema/broker. Repository evidence:
common/outbox.py, notification/public.py, notification/worker.py, ADR-001 and
Core API contract. See PLAN R1–R4 for four modifications/rejections.

P2 (coding-agent subtask): “Generate boundary, negative, failure-path and pairwise
tests for changed-post notifications; assert durable post, outbox, recipient scope,
retry and dedup. Preserve the two weak HTTP-status-only drafts in the review log.”
Output used: tests/vt034/pairwise.py, test_contract.py, test_postgres.py. W1 and W2
are shown in PLAN; replace their weak oracles with TC07/TC10 and explicit bounds.
The drafts were not executed as a supposedly valuable test suite.

P3 (coding-agent subtask): “Implement the smallest patch to pass the new spec;
reuse PostCreated's existing delivery checks for a new SOCIAL_POST_UPDATED event;
notify only when body differs; bound direct worker batch calls, preserve API.”
Output: 30 initial production/contract lines; diff reviewed before commit. Existing
PostCreated isinstance branches enforce current permissions/source existence for
both event types. Identical content is checked only after write authorization.

P4 (coding-agent subtask): “Run > to >= in an isolated temporary commit, check the
exact 1000 boundary failure, remove the worktree and prove original bytes intact.”
Output: executable mutation_check.py, mutation.patch, mutation.log/json. Killed
by TC06[1000]; boundary 1 stays green. No mutation remains on submitted branch.

P5 (coding-agent subtask): “Measure 60 concurrent real HTTP tasks, 10000 Unicode
characters, three waves; retain raw durations, statuses and durable-event counts.
Report local scope, absent browser and stopped-worker limitations honestly.”
Output: test_load.py and load.json. No fabricated production KPI.

## Environment fixes / reliability review

- Initial PostgreSQL launch did not persist across shell sessions; first setup
  attempts failed before business assertions. Replaced with a same-process ephemeral
  launcher. SQL_ASCII initdb returned bytes to psycopg; initialize UTF-8 explicitly.
  Final red.log is the corrected run: no setup errors, 9 genuine failures/8 passes.
- Ruff found a reused-fixture import and late-bound load-loop variables. Corrected
  noqa placement and bound barrier/body/wave as default arguments; final Ruff passes.
- tsx CLI attempted a forbidden Unix IPC socket. Preserved web-check.log, used Node
  --import tsx for the same files (260 passes). No product permission was weakened.
- CLI git push lacked credentials; GitHub API published equivalent source trees.
  evidence/execution.json maps local execution to remote commits and blob hashes.
- Repeat load overlapped with Web build; preserved load-repeat.json separately.
  Final load.json is a fresh isolated run after build completed. No threshold was
  changed to make a result pass.

## Two plausible AI outputs that need evidence

1. Catching all notification errors in the producer looks resilient but would lose
   atomic outbox intent. TC09 must prove enqueue failure rolls back, while TC10
   separately proves committed edits survive worker failures.
2. A pairwise generator and HTTP 200 oracle can look comprehensive yet never run
   a successful max-size edit with delivery failure. Independently audit all 37
   pairs and supplement with TC07/TC10/TC14; do not count masked pairs as proof.

Evidence paths, commands, residual risks and pending human/team review are in README.
The PDF reflection is an AI-assisted draft for the student to verify and own.
