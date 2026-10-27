---
name: lumi-frontend-orchestrator
description: "Coordinate Lumi's Next.js frontend on frontend1: AGY Gemini 3.8 Flash High generates bounded UI, while Codex owns business logic, data integration, permissions, tests, review, contracts and Git safety. Gemini 4 Argon may perform read-only architecture reviews. Use when auditing, planning, implementing, or verifying apps/web in the SE2026_T09_RAG_course_assistant repository."
---

# Lumi frontend: AGY authors UI, Codex owns logic and integration

You are the sole integrator and acceptance authority. Antigravity (`agy`) is a tool, **not an authority on requirements**. Your output must be working, verified code or a precise, evidence-backed blocker; don't declare functionality complete based on a successful AGY response.


## Current user-authorized ownership

The user explicitly requested AGY for UI generation and Codex for business logic. This takes precedence over generic worker suggestions in the bundled examples. Use `gemini-3.8-flash-high` for scoped UI/CSS/presentational components. Codex implements and wires data/session/permissions/async controllers and validates the result. `gemini-4-argon-high` is available for bounded read-only architecture or independent review; do not delegate business-logic writes to it under this ownership split. Do not reconfigure the global Codex/AGY model or provider.

The Codex skill is installed globally and in this repository. Run the bridge from the repository's `.agents/skills/lumi-frontend-orchestrator/scripts` path; the global copy is for discovery. Include this skill's repository path in each AGY task so the worker reads the same constraints. Current user authorization to finish the frontend includes necessary reversible implementation and checks; do not repeat approval requests for already-authorized work.

## Activation and prerequisites

1. Work only in the `4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant` local checkout, branch `frontend1` (or an explicitly authorized feature branch based on it). Read root `AGENTS.md` and `apps/web/AGENTS.md`; never replace root rules. Confirm `git branch --show-current`, `git status --short`, `git rev-parse HEAD` and preserve pre-existing changes.
2. Read `references/repo-baseline.md`, `apps/web/docs/FRONTEND.md`, `docs/architect/BUSINESS_RULES.md`, relevant service contracts, `apps/web/src/lib/data/integrations.ts`, routes and affected feature implementations. Read the *relevant parts*, not every file blindly.
3. Verify local `agy --version`, `agy models`, `codex --version`, `node --version` and Node >=22.17.0. On Windows, run `scripts/check-environment.ps1`. Available model slugs must be checked locally, never silently substituted.
4. Default orchestration reasoning = xhigh; increase to max only for cross-service conflicts, complex exam state machines/security, or independent final architecture review. Avoid wasting expensive reasoning on routine CSS changes.

## Critical architectural boundaries

- This is a Next.js 15 / React 19 / TypeScript 5 frontend. `apps/web/app/**/page.tsx` are thin route wrappers; implement actual behavior in `apps/web/src/features` and shared libraries.
- `docs/architect/BUSINESS_RULES.md` wins over designs, snapshots, AI guesses and mock fixtures. MVP: one school; grades 6–12; roles ADMIN, LECTURER (display Giáo viên), STUDENT; no join codes or free student sign-up. Permissions are enforced by backend, UI guards alone are insufficient.
- `apps/web/src/lib/data/port.ts` owns adapter surface. Product components may not fetch directly or import fixtures. `src/lib/data/index.ts` alone imports `@data-adapter`, bound by `next.config.mjs`. Never introduce live/mock blending, fallback-on-error to fixtures, or client secrets.
- `NEXT_PUBLIC_DATA_MODE=mock` is only a *dev preview*. Real release is `live`, must pass `npm run build` including `check:boundaries` and `check:release`. Do not remove or weaken these gates.
- `src/lib/data/integrations.ts` declares current service readiness. Do not turn `pending-contract` into live calls or invent API/schema/policies. For a pending API, implement UI states and explicitly mark integration blocked until a real contract is approved; Codex resolves contract evidence before any integration.
- Preserve auth semantics: in-memory access token, HttpOnly refresh cookie, same-origin `/api/v1`, approved proxy allowlist, `WEB_ORIGIN`, role checks and existing error semantics. A network outage never becomes successful mock data.
- Never change `services/`, backend contracts, docs business rules, migrations, CI/security settings or Git history as a side effect of frontend work. Propose cross-boundary changes for explicit approval.

## Orchestration loop (mandatory)

**0. Baseline:** Capture SHA, status, relevant existing tests and initial `npm run check`. If dependencies are missing, use `npm ci` *only with approval for dependency installation*, then record that action. Never overwrite an existing unclean worktree.

**1. Audit:** Inventory a route against the actual feature, navigation, states, permission boundary, mock/live data ports, and approved business rules. Use `agy` Flash for straightforward inventory if needed, Argon for complex gap analysis. Codex must verify findings in source. Record task status in `docs/ai/FRONTEND_ORCHESTRATION.md` or your report; label as `implemented`, `UI-only`, `blocked-contract`, `missing`, or `unverified`, without inventing progress.

**2. Task contract:** Before delegation, create a small `.md` task file outside tracked product code (or under a deliberately ignored local scratch directory). Follow `references/task-contract.md`. One feature or cohesive vertical slice per task. Specify exact editable paths, prohibited paths, acceptance criteria, and honest blocked paths. Never ask AGY to "finish the whole frontend" in one invocation.

**3. Choose worker:**

| Work | Worker | CLI profile |
| --- | --- | --- |
| Visual UI, CSS, responsive, presentational components, routine tests | Gemini 3.8 Flash High | `-Phase Implement -Worker flash` |
| Authorization, exam state machines, integration and cross-feature logic | Codex implementation; optional Gemini 4 Argon High read-only review | `-Phase Audit/Review -Worker argon` |
| Independent review of an implementation | Prefer a different model than implementer | `-Phase Review -Worker argon` (if Flash implemented) |
| Acceptance, resolving conflicts, final API and security decisions, `npm run check/build`, commit recommendations | Codex | never delegate authority |

**4. Execute via Windows bridge:** From repository root use `powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\skills\lumi-frontend-orchestrator\scripts\invoke-agy.ps1 -Phase Implement -Worker flash -TaskFile docs\ai\task-sample.md`. For audit/review, choose `-Phase Audit` or `Review`; the bridge enforces model slugs and interprets the JSON terminal status. `SUCCESS` is **not** evidence of correct edits. No `--dangerously-skip-permissions`.

**5. Review changes:** Inspect `git diff --stat`, `git diff -- apps/web`, `git status --short`. Look for edits outside the agreed scope, TODO stubs, dead links, fake success paths, unauthorized API paths, security mistakes, broken boundaries, altered package lock, hidden mock fallback, fake test claims. If edits overlap another worker or are outside scope, stop and resolve manually; do not blindly reset other people's changes. AGY does not commit, push, merge or create PRs.

**6. Verify:** Codex runs `npm run check` and `npm run build` in `apps/web` with live mode, plus `git diff --check` and focused UX/manual/browser tests. Use `scripts/qa-web.ps1` on Windows. For real backend interactions require an actual configured Core/API and browser evidence; mock tests do not certify live integration. Classify network/contract unavailable honestly.

**7. Repair loop:** When a gate fails, give AGY one narrow repair task containing the exact error and affected files. Cap to 2 AGY repair iterations for the same failure, then Codex diagnoses/restructures or records a blocker. Avoid infinite recursion or parallel cross-edits.

**8. Report:** Always provide changed files, worker used, actual shell commands + pass/fail, remaining blockers, and verification status per route. No commits/push/PR unless the user explicitly approves. Protect source secrets and never paste `.env.local`, cookies or tokens into an AGY prompt or log.

## Efficiency rules

- Run AGY sequentially in the same worktree. Parallelize only independent *read-only* audits; for parallel writes use separate Git worktrees with clear ownership and Codex-controlled cherry-picking after verification.
- Make AGY read only relevant source and docs, with short acceptance criteria. Do not repeat full monorepo context in every prompt. Prefer Flash by default, escalate to Argon only for complexity or failed attempts. Cross-check a sample with independent review rather than always doing two identical reviews.
- The bridge produces JSON logs under the current Windows user profile. Keep them private, never commit. Check runtime `agy models` and remaining plan quota before expensive runs. AGY CLI's own `--effort` is different from Codex's xhigh/max; the `*-high` model slugs are intentional.
- Treat stdout success status, file diff, passing tests, visual verification, and backend readiness as five separate signals.

## Supporting references

- `references/repo-baseline.md`: verified checkout details and contract boundaries
- `references/task-contract.md`: ready-to-use task definition and anti-hallucination guidance
- `references/quality-gates.md`: verification and evidence matrix
- `templates/task.example.md`: bounded first task
- `schemas/review.schema.json`: JSON schema used for read-only audit/review
- `scripts/check-environment.ps1`, `scripts/invoke-agy.ps1`, `scripts/agy-process.py`, `scripts/qa-web.ps1`: Windows helpers. The Python launcher preserves literal argv for multiline/JSX prompts; the bridge rejects denied actions and empty responses and retains private logs.
