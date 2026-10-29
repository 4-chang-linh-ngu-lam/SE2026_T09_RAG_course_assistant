# Frontend architecture and backend handoff

## Current implementation

The frontend implements the 71 product routes in the approved UI map. There are 72 App Router `page.tsx` files because `app/page.tsx` is the extra session redirect. The 104 design references include responsive variants, modal states and seven reference boards; they are not 104 product URLs or a blanket claim that every canvas state has passed visual acceptance.

The shared shell owns role navigation, breadcrumbs, the current class header/tabs, reader/focused layouts, session/access boundaries, mobile navigation and dialog focus. Feature entries own Identity, accounts/imports, Classroom administration, classroom home/history, Social/calendar, notifications, Document/notes, Tutor, Practice, official Assessment, assignments/grading and Intelligence.

Development preview implements complete interactions for these journeys: Student provisioning/activation/recovery, staff invitation, real CSV/XLSX parsing and import confirmation, enrollment/transfer/archive/restore, feed/calendar, source grants/versions, reader notes/bookmarks, Tutor conversations/stream cancellation, four Practice/Assessment question types, serialized saves and unknown-outcome reconciliation, immutable published versions and confirmed receipts, assignment file bytes and grading/correction approval, confirmed learning evidence, personal-data review/copies and real PDF/XLSX report artifacts. Source-library upload preview currently models file metadata/processing; it does not certify a real uploaded document or extraction service.

These flows run in the explicitly selected in-memory development adapter. Full document reload resets that adapter; same-document navigation and explicit sign-out/sign-in retain the preview's shared business store. Local drafts are scoped to actor/resource/version and are volatile. No browser preview certifies durable service persistence, real AI, email delivery or school production readiness.

Identity transport/profile/self-request/Student-provisioning clients use the documented Core operations. Real Core verification remains separate. Non-contracted capabilities have typed unavailable live adapters. In particular, listing/creating a personal-data request is contracted; downloading a prepared copy, Admin review and processing still need contracts. `src/lib/data/integrations.ts` records this operation-level distinction.

Access tokens stay in memory. Refresh cookies remain HttpOnly under `/api/v1/auth`, with one refresh in flight and no blanket mutation replay. Auth return links preserve only allowed source/page/conversation/filter context, discard secrets and unknown queries, and retain role checks. Server permission decisions remain authoritative.

## One data source, no fallback

`src/lib/data/port.ts` is the frontend port. Only `src/lib/data/index.ts` imports `@data-adapter`. `next.config.mjs` binds that alias to `src/lib/data/live.ts` for live builds, or `dev/mocks/adapter.ts` for explicit development preview. TypeScript checks both against the same port through an ambient declaration; tsconfig must not map this alias to a concrete adapter, because that overrides runtime selection. Preview compiles into `.next-preview`; live uses `.next` to keep artifacts separate. Product pages never import fixtures and never call fetch directly.

`NEXT_PUBLIC_DATA_MODE` accepts only `live` or `mock`; missing means live. Mock is rejected for production build and start. There is no per-feature override, query/localStorage toggle, catch-to-fixture branch or hybrid mode. Fixture data lives exclusively in `dev/mocks`; mocks are excluded from the live dependency graph. `npm run check:boundaries` checks imports/network/storage. `npm run check:release` scans `.next/static` and `.next/server` for the fixture canary; run `npm run build` for the complete release gate. These controls reduce regressions; they do not replace review of newly added code/data sources.

All sample business identities, file rows and counts belong to the development fixture module. Product navigation/labels/static UI copy are not mock data. Build with live configuration after any preview run; never ship a dev server or bypass the build gate.

## Backend boundary

The browser uses same-origin `/api/v1`. The Next route handler forwards only allowlisted operations documented in [Core API Contract](../../docs/architect/microservices-v1/core/API_CONTRACT.md): Identity, Student provisioning, Classroom, Social, Calendar, Notification, staff administration and Student import. It reads `CORE_API_URL` on the server, preserves cookies, Origin and correlation/retry metadata, refuses external redirects and never forwards service keys. Admin mutations forward only the enumerated reason/idempotency headers. Configure `WEB_ORIGIN` to the exact browser-facing scheme/host/port; state-changing requests must match it. Missing/invalid origin configuration fails closed. Configure Core CORS for that browser origin, not `http://core:8000`. Use HTTPS/secure cookies in a real deployment.

Live adapters validate Core response DTOs and do not fall back to preview fixtures. Classroom administration uses versioned roster replacement, one-student homeroom transfer, versioned AUTO sync and MANUAL roster replacement. AUTO overrides and legacy account School mapping remain unavailable. Student import reads the Core status endpoint after an unknown confirm outcome; that GET never retries the import and completed status never returns activation codes. Admin global audit is read from Core; the UI hides Classroom-specific history panels when the API does not provide resource-scoped history. Data-request review/fulfillment remains deferred. `src/lib/data/integrations.ts` records these operation-level boundaries.

For each future capability:

1. Approve its public contract and current permission/ownership rules in the owning service. Obtain real OpenAPI/request/response/error examples without secrets.
2. Add the operation/decoder and narrowly scoped proxy destination (or approved API entry design). Keep transport in `lib/api`, never service credentials in client code.
3. Implement the live capability adapter and feature UI states; remove the explicit unavailable outcome for that capability. Map wire DTOs into frontend view models, not the reverse.
4. Test the live path against that service, especially 401/403/404/409, timeout/unknown outcome, cancellation, validation, empty and malformed response. No automatic replay of important mutations. Student create/issue-code/activate reject generic Idempotency-Key.
5. Build in live mode; require boundary and release scan passes. Inspect Network: API down must show an error, not a sample row. Record actual operation-level integration evidence.

## Run and verify

From `apps/web`, run `node scripts/dev-mock.mjs --hostname 127.0.0.1 --port 4179` for explicit development preview. Use `npm run dev` for live mode with the documented server environment. Do not deploy the preview server or build with mock mode.

Current acceptance (29 October 2026): `npm run check` passes boundaries, TypeScript and **245 behavioral tests**. The live `npm run build` and release fixture-canary scan are the release gate. Chrome mock preview smoke checked **71 route IDs** (68 seeded routes plus 3 UI-created resources); focused journeys passed **214 assertions** with selected screens at 1440/768/390/320px. See [FRONTEND_COMPLETION.md](../FRONTEND_COMPLETION.md) for preview evidence and limitations. These checks do not replace real Core/database/browser journey evidence.

Historical evidence from 20 October 2026: production browser smoke checked 71 mapped URLs and 18 transport/access/failure/UI assertions against an isolated Core contract stub; this is not a real Core deployment.

The external implementation ledger and current evidence live under `D:/app/cnpm/frontend/artifacts/frontend-implementation`. See `COMPLETION.md`, `status.json` and `antigravity/qa/release-final/gates.json`. Journey evidence distinguishes actual browser interactions, unit tests, static route availability and unavailable live integrations. Selected screens were inspected at390/1024/1440; no blanket all104-canvas visual certification is claimed.

## Agent workflow

Read repository `AGENTS.md`, `apps/web/AGENTS.md` and `.agents/skills/lumi-frontend-orchestrator/SKILL.md`. The same skill is installed for Codex. Per the user's instruction, AGY Flash authors bounded UI; Codex owns business logic, adapters, permissions, async state, integration and acceptance. Argon is available for read-only review. The repository Windows bridge preserves multiline/JSX arguments and rejects empty or permission-denied responses. No global model/provider/approval setting was changed.

## Remaining integration work

Document, AI Tutor, Learning and Learner Intelligence remain unavailable in live mode until their contracts and services are implemented. Admin data-request fulfillment/report exports remain unavailable or policy-deferred; student history and detailed resource-scoped Classroom audit still need read APIs. Staff invite/recovery delivery requires an operator-configured SMTP provider. A successful web build is not evidence that the deployed Core, database, email delivery or first-Admin onboarding is operational.


## Local development compiler

`npm run dev:mock` uses Next.js 15 Turbopack to reduce initial development compilation. Both `turbopack.resolveAlias` and `webpack.resolve.alias` select the same mode-specific `@data-adapter`. The mock runner still forces mock mode and refuses production; the live build command and release scan are unchanged. Output stays in `.next-preview` for mock and `.next` for live.

Stop the current server before changing compilers or restarting after this script update; never run two servers writing the same output directory. `npm run dev:mock:webpack` keeps the previous Webpack runner available for diagnosing bundler-specific issues. Neither compiler eliminates all cold compilation. Warm route GET times measure development server response, not complete click-to-content or backend latency. Keep the dev cache between ordinary restarts; do not delete `.next-preview` as a routine speed-up step.
