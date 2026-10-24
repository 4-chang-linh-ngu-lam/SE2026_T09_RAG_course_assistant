# Verified branch snapshot: `frontend1` (2026-10-20)

Repository: `4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant`
Git tree snapshot SHA: `9dc547c467c093940fcdc9873a14cf45ca1f6a28` (tree; re-read HEAD locally)

The `apps/web` subtree contains **236 tracked files, including 72 tiny App Router `page.tsx` route entry points** and **15 `tests/*.test.ts` files** (GitHub tree inspection). Tiny entry points typically call `RouteScreen`. These counts are not proofs of complete pages; actual features live under `src/features`.

## Tech and commands

- Next.js `15.5.12`, React `19.1.0`, TypeScript `~5.9.3`, Node `>=22.17.0`.
- `npm run check`: boundary check + TS typecheck + tests.
- `npm run build`: boundary check + Next live build + release canary scan.
- `npm run dev:mock`: isolated mock preview only; not a live business-flow test.
- `npm run dev`: live mode by default; real backend requires server-only `CORE_API_URL` and exact `WEB_ORIGIN`.
- Existing tests: accounts, assessment-state, assignment-transitions, classroom-admin, classroom-history, integration-boundary, intelligence-transitions, live-session, notification-read-controller, reader-content, reader-tutor-ownership, shared-projection, stage1/2/3a transitions.

## Important source files

- `AGENTS.md` repo root: existing, higher-priority engineering policy; **do not overwrite**.
- `docs/architect/BUSINESS_RULES.md`: top-level product truth.
- `apps/web/docs/FRONTEND.md`: current frontend implementation and live integration limitations.
- `apps/web/src/features/index.tsx`: dispatch feature ownership.
- `apps/web/src/components/route-screen.tsx`: route resolution, session/UX guards and feature composition.
- `apps/web/src/config/routes.ts` / route config (verify actual file path before changing).
- `apps/web/src/lib/data/port.ts`: adapter API for UI.
- `apps/web/src/lib/data/integrations.ts`: readiness matrix.
- `apps/web/src/lib/data/live.ts`, `dev/mocks/adapter.ts`: separate data sources.
- `apps/web/src/lib/api/operations.ts`: **Identity-only** allowlist; no guessed endpoints.
- `apps/web/next.config.mjs`: selects `@data-adapter` based on live/mock mode.

## Explicit incomplete states, per `FRONTEND.md`

- Verified locally: 71 mapped product routes, 72 `page.tsx` files because `app/page.tsx` is the extra session redirect. The 104 design references include responsive variants and 7 reference boards; they are not 104 product URLs. Route count does not certify every screen state.
- Identity clients implemented but real Core integration must be verified separately.
- Classroom/Social/Notification/Administration/Document/Tutor/Learning/Intelligence operations are generally `pending-contract` in current integration registry.
- Feature-specific editors and actual uploads/streams/timers/submission/grade/export/import/roster paths are not verified as production complete.
- Official assessments must respect timer/resume policy and avoid Tutor during assessment, subject to the controlling business spec.

## Never assume

No design file guarantees runtime completeness. Mock UI data is not live backend support. The root README includes planned business capabilities and warns that many are not yet implemented. Re-check local source, actual contracts, environment and tests before asserting any individual capability is delivered.
