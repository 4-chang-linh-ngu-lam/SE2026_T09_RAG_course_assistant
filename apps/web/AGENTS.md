# Lumi Web agent instructions (additive to repository-root `AGENTS.md`)

Use `$lumi-frontend-orchestrator` when coordinating or delegating frontend work to Antigravity CLI. Codex owns architecture decisions, quality gates and final integration; AGY makes bounded edits only.

- Read `docs/FRONTEND.md`, the repository's `docs/architect/BUSINESS_RULES.md`, and `src/lib/data/integrations.ts` before editing relevant features.
- `app/**/page.tsx` are minimal route entry points; implement actual UI in `src/features`, shared `src/components`, or explicitly owned libraries.
- No direct business network calls or fixture imports from feature pages. Use `src/lib/data/port.ts` through `src/lib/data/index.ts`. Preserve the `@data-adapter` single entry and `next.config.mjs` live/mock isolation.
- The approved Core surface is the exact 63 operations in `src/lib/api/operations.ts`: Identity, Notifications, Classroom, Social/Calendar and Administration/import, including eight metadata GETs authorized when completing Core. See `docs/CORE_MISSING_READS_PROPOSAL_2026-10-22.md` and Core API_CONTRACT. Further endpoints/services require their own contract approval; health/internal/register stay outside the browser proxy.
- Keep `NEXT_PUBLIC_DATA_MODE=mock` limited to local preview; no mock production build, fixture fallback, fake persisted success or fabricated evidence.
- Keep session, permission and API failure semantics; the server enforces roles and ownership. Never display Student join code/self-register or invent new roles.
- Write meaningful loading, error, empty, 401/403/409, validation and responsive/keyboard states appropriate to the task.
- Preserve uncommitted work and avoid edits to services, migrations, root rules and unrelated modules. AGY never commits or pushes.
- Validation from this folder: `npm run check` and `npm run build` in **live** mode; report exact exit codes and any blocked tests. A passing build is not evidence of a real backend journey.

## Current task ownership

AGY generates and refines UI in an explicit file allowlist. Codex owns business logic, adapters, session/permission state machines, integration and acceptance. Gemini 4 Argon is reserved for optional read-only review. Read `.agents/skills/lumi-frontend-orchestrator/SKILL.md` from the repository root before an AGY task. Do not change global model/provider or approval settings.
