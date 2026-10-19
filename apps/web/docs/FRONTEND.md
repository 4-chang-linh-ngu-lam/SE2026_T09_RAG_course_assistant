# Frontend architecture and backend handoff

## Implemented scaffold

- 71 browser route entry points generated from the approved mapping; 7 responsive canvases and 7 reference boards do not add product routes. 67 routes have direct design sources, 4 derive from shared templates.
- One shell/navigation configuration: role sidebar, compact class header/tabs, focused/reader shell, history banner, auth layout, loading/error/access boundaries, responsive navigation dialog and basic form controls.
- Separate feature ownership entry points for Identity, Classroom, Social, Notification, Administration, Document, Tutor, Learning and Intelligence. Unfinished pages show honest empty/unavailable states; they are not finished screen implementations.
- Contract-backed Identity transport, DTO decoders and adapters: login/refresh/logout/profile, activation/reset/forgot, personal-data requests and Admin Student provisioning. These clients are implemented; integration with a real configured Core must be verified separately.
- Access token memory only. Refresh cookie remains HttpOnly at `/api/v1/auth`. One refresh in flight; no blanket request replay. Protected route roles come from `/users/me`, not URL/mock flags. Role checks are UX guards, not backend permission enforcement.

## One data source, no fallback

`src/lib/data/port.ts` is the frontend port. Only `src/lib/data/index.ts` imports `@data-adapter`. `next.config.mjs` binds that alias to `src/lib/data/live.ts` for live builds, or `dev/mocks/adapter.ts` for explicit development preview. TypeScript checks both against the same port through an ambient declaration; tsconfig must not map this alias to a concrete adapter, because that overrides runtime selection. Preview compiles into `.next-preview`; live uses `.next` to keep artifacts separate. Product pages never import fixtures and never call fetch directly.

`NEXT_PUBLIC_DATA_MODE` accepts only `live` or `mock`; missing means live. Mock is rejected for production build and start. There is no per-feature override, query/localStorage toggle, catch-to-fixture branch or hybrid mode. Fixture data lives exclusively in `dev/mocks`; mocks are excluded from the live dependency graph. `npm run check:boundaries` checks imports/network/storage. `npm run check:release` scans `.next/static` and `.next/server` for the fixture canary; run `npm run build` for the complete release gate. These controls reduce regressions; they do not replace review of newly added code/data sources.

All sample business identities, file rows and counts belong to the development fixture module. Product navigation/labels/static UI copy are not mock data. Build with live configuration after any preview run; never ship a dev server or bypass the build gate.

## Backend boundary

The browser uses same-origin `/api/v1`. The Next route handler forwards only an allowlist of Identity operations actually implemented in the current repo. It reads `CORE_API_URL` on the server, preserves cookies, Origin and correlation/retry metadata, refuses external redirects and never forwards service keys. Configure `WEB_ORIGIN` to the exact browser-facing scheme/host/port; state-changing requests must match it. This avoids relying on Next's internally constructed request URL behind a proxy. Missing/invalid origin configuration fails closed. Configure Core CORS for that browser origin, not `http://core:8000`. Use HTTPS/secure cookies in a real deployment. No backend access/permission/schema changes are introduced here.

The current repo still marks Classroom payloads and other services as proposed. The newer UX snapshot's IMPLEMENTED label is not applied to this checkout. Missing operations therefore remain unavailable and the proxy refuses them; no guessed endpoint is called. `src/lib/data/integrations.ts` records current readiness.

For each future capability:

1. Approve its public contract and current permission/ownership rules in the owning service. Obtain real OpenAPI/request/response/error examples without secrets.
2. Add the operation/decoder and narrowly scoped proxy destination (or approved API entry design). Keep transport in `lib/api`, never service credentials in client code.
3. Implement the live capability adapter and feature UI states; remove the explicit unavailable outcome for that capability. Map wire DTOs into frontend view models, not the reverse.
4. Test the live path against that service, especially 401/403/404/409, timeout/unknown outcome, cancellation, validation, empty and malformed response. No automatic replay of important mutations. Student create/issue-code/activate reject generic Idempotency-Key.
5. Build in live mode; require boundary and release scan passes. Inspect Network: API down must show an error, not a sample row. Record actual operation-level integration evidence.

## Scope remaining

The generic feature surfaces are composition points, not completed 65 page-component designs. Finish each module from its selected HTML/PNG/state/journey contract. No file upload, Tutor stream, Assessment runner, actual timer/submission/grade/export/import/roster operation is claimed implemented. Forms include basic unsaved-beforeunload/link guards; feature-specific draft persistence and browser Back recovery must be designed before real Learning attempts/editors. Public tokens from email reset links are captured once into memory and removed from the URL. Issued activation code is never persisted.

Full verification includes a real Core environment and browser journeys; a successful build or development fixture preview does not certify those operations. Update the external frontend implementation status ledger per route as the detailed features land.
