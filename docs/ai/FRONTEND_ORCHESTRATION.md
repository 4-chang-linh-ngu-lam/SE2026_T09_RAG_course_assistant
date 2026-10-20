# Lumi frontend orchestration ledger

Branch `frontend1`; integrator Codex. AGY Flash authors UI; Codex owns logic, state, ports, permissions and acceptance. Argon performs optional read-only review. The skill is installed globally for Codex and in this repo for agents; no global model/provider/approval setting was changed.

The 71 mapped product routes are implemented. The 72nd `page.tsx` is `app/page.tsx`, the root session redirect. Detailed state/viewport acceptance and live service readiness are separate from route availability.

## Current acceptance

170/170 tests plus boundary/TypeScript checks passed. Live production build and release canary scan passed. Production browser smoke checked71 URLs and18 assertions against an isolated Core contract stub. Browser suites cover accounts/imports, Classroom ACK/access changes, source/history, Reader/Tutor, notifications, Practice/official Assessment, assignments/grading and Intelligence. Read current external `frontend-implementation/COMPLETION.md` and `antigravity/qa/release-final/journey-index.json` for exact counts and limits; do not infer all104 design states were certified.

## Integration status

Identity/profile/self data-request/Student-provisioning clients are contracted but still require real Core integration verification. Most other services, including personal-data copy delivery/review/processing, remain pending contract. Their live adapters fail honestly with unavailable outcomes. Explicit preview uses an isolated in-memory adapter, never a live fallback. No backend contract or business-rule changes were included.

## Working protocol

Read root/web AGENTS and `.agents/skills/lumi-frontend-orchestrator/SKILL.md`. Use the repository Windows bridge with an exact UI file allowlist. Codex implements logic and checks every diff. Only one writer at a time; read-only review may run alongside clearly recorded Codex integration. Shell checks are owned by Codex; AGY UI uses file tools. Treat denied actions, empty output and SUCCESS separately from actual acceptance. The bridge captures JSON with safe literal Windows argv; it never changes permission settings, commits or pushes.

For a future live capability, obtain the approved contract/permission/error examples, implement the narrow adapter/decoder/proxy operation, test the real service, then rerun live release gates. Preserve unrelated work and the no-mock-fallback invariant.
