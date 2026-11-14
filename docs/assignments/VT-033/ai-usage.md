# AI Usage Log - actual session

Tool: Codex, GPT-6 family (exact deployed model build not exposed). The student is
Mai Huy Hoàng,23001878. No student/owner approval is inferred from AI verification.
The complete real user prompt is preserved locally in `ai-main-prompt.md`, excluded from Git.
Initial proposals are preserved in [spec-and-plan.md](spec-and-plan.md); the separate
read-only Codex agent's findings are recorded in [plan-review.md](plan-review.md).
User explicitly chose “Dùng một agent chỉ đọc để review kế hoạch” before it spawned.

| Actual action/prompt context | AI output and disposition | Evidence |
|---|---|---|
| User's full local-first VT033 master prompt | Implement locally, test first, isolated PG16, authorization mutation, load120, PDF and Draft PR | Full prompt file, environment metadata |
| Initial AI plan | P1 shared helper parameterization; P2 env per request; P3 mocked RED; P4 reuse class harness | Actual candidate statements saved before production changes |
| User chose independent read-only agent | Review plan against baseline source/rules/contracts; no edits/tests/Git mutation;>=2 corrections with citations; assess hidden risks | plan-review.md; user choice; agent vt033_plan_review |
| Independent review | P1 corrected to local dependency; P2/P4 rejected; P3 accepted only for parameter routing, strengthened with PG outcomes | Baseline source citations; recorded before feature patch |
| AI wrote BVA/API/PG tests | Exact Pagination for RED plus IDs/payload/read/cursor/unread/created_at and persisted state | RED6dd9ebf, logs01-red-*; new38 instances |
| AI patched two production files | Existing Settings Field + Notification-local dependency; shared helper/auth/repository/service unchanged | Implementationd987016;69 Notification tests passed; lint/format |
| AI wrote mutation runner | Detached local worktree; remove one predicate; assert persisted read_at; exact-byte restore in finally | 3pass→3business-state failures→3pass; hashes equal; no mutant source pushed |
| AI investigated Windows baseline failures | Initial sandbox hid installed Python; approved host check found3.12.0. Initial full suite failed4+1error; existing3.12.14+UTF8 corrected targeted4cases, without package version changes | 00-baseline-full,00-baseline-email-utf8,02-environment-recovery,02-green-recovered-baseline-cases |
| AI wrote Notification HTTP load |120 actual tasks/barrier, own synthetic data/JWT, actual app/Identity/PG, client and backend latency; no external AI |07-smoke/07-load artifacts, executable source hashes |
| AI investigated client/backend latency gap | Initial full HTTPX0.28.1 profile FAIL (p95 client17578.75ms,3541requests,0errors). Added explicit client choice and compared existing HTTPX2 dev dependency, same app/DB/pool/target |07-load-httpx.json preserves FAIL;07-load.json is the separately measured HTTPX2 profile; no new dependency |
| AI tested established pool profile | HTTPX2/default5+10 also FAIL:7016requests,524HTTP503+2transport errors, p95 client3472.58ms. Compared Core tests README15+0 profile, maximum15/admission14 unchanged |07-load-httpx2-default-pool.json preserves FAIL;07-load.json records final15+0 measurement; no production-default/target/workload change |
| AI drafted documentation/reflection/PDF | Evidence-driven values;318-word Vietnamese reflection draft; embedded font and all-page render QA |README,traceability,submission.json,PDF QA |

## Independent reviewer prompt actually sent

> User explicitly requested one read-only agent for independent plan review. Review
> docs/assignments/VT-033/spec-and-plan.md against actual baseline source, business
> rules and Core contracts. No file edits, no subprocess tests while baseline being
> prepared, no Git mutations. Return concrete independent review with>=2 real
> initial AI candidates P1-P4 corrected/rejected, citations file:line and baseline SHA,
> final minimal implementation recommendation, hidden test/load risks, confirmation
> no new business rule conflict or state exact conflict. Do not claim human approval.
> Main agent will save your exact review. Need this before any production patch.

The review file records the agent's decisions, citations and warnings in a compact
form; it is an AI independent review, not a human sign-off.

## Two plausible AI suggestions that were not trustworthy by themselves

1. **A mocked service returning200** can pass even when the real repository lacks
   authorization. Such tests are retained only for routing. The PG security test
   checks B's persisted `read_at` before the HTTP assertion; the actual mutation
   proved that the oracle detects the missing predicate for defaults1/2/100.
2. **Increasing a `--users` cap** does not create120 actors or test the requested
   endpoint/latency metric. The old fixture creates only100 actor pairs and gates
   backend500ms. The new harness measures actual tasks/peak in-flight, exact own
   notification contents and client3500ms; smoke is explicitly not acceptance.

An additional test-generation correction: a namespace fixture's default repr could
include synthetic JWT fragments in a failing traceback. Before committing evidence,
the fixture was changed to a credential-free repr, JWT redaction was added to the
recorder, and PostgreSQL RED was rerun with a short traceback. No failed assertion
was relabeled as a pass. Log trailing whitespace was normalized, not test outcomes.

Human review remains required for the report/reflection/responsibility statement,
shared Settings and Notification/Identity/Common ownership. The PR is a draft and
must remain unmerged pending team review.
