# Frontend architecture and backend handoff

Latest login/email flow: [role-specific activation and emailed onboarding links](CORE_EMAIL_LINK_FLOW_2026-10-23.md). Student activation remains visible only on the Student login tab; staff follow the configured-origin email link. Verification: 329 Web tests, 51 focused backend tests, 22 HTTP groups and six real Chrome groups. Earlier reports below retain their dated scope and counts.

Latest functional integration work: [Web–Core connection fixes, 23 October](CORE_WEB_CONNECTION_FIXES_2026-10-23.md). Live home/overview now use scoped Core class reads and distinguish missing other-service summaries. UUID/resource matching and management acknowledgement/reconciliation states are corrected. Performance optimization is deferred separately.

Current functional acceptance (23 October 2026): [connection follow-up](CORE_WEB_CONNECTION_FIXES_2026-10-23.md) records324 Web tests, a production live build,22 HTTP groups and five real Chrome interaction groups after the approved WSL clock reset. The [runtime follow-up](CORE_RUNTIME_FOLLOWUP_2026-10-23.md) records the earlier115 selected backend regressions,317 Web tests and load-methodology investigation; the [earlier Core completion report](CORE_COMPLETION_2026-10-23.md) retains the historical full backend run. Backend suites were not rerun for these Web-only logic repairs. Performance work is deferred and external SMTP remains unverified.

## Current implementation

The frontend implements the 71 product routes in the approved UI map. There are 72 App Router `page.tsx` files because `app/page.tsx` is the extra session redirect. The 104 design references include responsive variants, modal states and seven reference boards; they are not 104 product URLs or a blanket claim that every canvas state has passed visual acceptance.

The shared shell owns role navigation, breadcrumbs, the current class header/tabs, reader/focused layouts, session/access boundaries, mobile navigation and dialog focus. Feature entries own Identity, accounts/imports, Classroom administration, classroom home/history, Social/calendar, notifications, Document/notes, Tutor, Practice, official Assessment, assignments/grading and Intelligence.

Development preview implements complete interactions for these journeys: Student provisioning/activation/recovery, staff invitation, real CSV/XLSX parsing and import confirmation, enrollment/transfer/archive/restore, feed/calendar, source grants/versions, reader notes/bookmarks, Tutor conversations/stream cancellation, four Practice/Assessment question types, serialized saves and unknown-outcome reconciliation, immutable published versions and confirmed receipts, assignment file bytes and grading/correction approval, confirmed learning evidence, personal-data review/copies and real PDF/XLSX report artifacts. Source-library upload preview currently models file metadata/processing; it does not certify a real uploaded document or extraction service.

These flows run in the explicitly selected in-memory development adapter. Full document reload resets that adapter; same-document navigation and explicit sign-out/sign-in retain the preview's shared business store. Local drafts are scoped to actor/resource/version and are volatile. No browser preview certifies durable service persistence, real AI, email delivery or school production readiness.

The 63 approved Core operations include Identity, Notifications, Classroom, Social/Calendar and Administration/import, with eight metadata reads authorized to complete Core. Ten account/classroom management routes now use current accounts, year/semester/course labels, homerooms, roster, teachers and real class/roster versions. Existing class lists, feed/comments, calendars, audit and the three Admin forms remain live. Comment editing uses the existing author-only Core contract. Strict decoders and `adapter.core` preserve wire DTOs without fabricating preview revisions or roles. All live clients share one in-memory credential/session controller; refresh verifies the known actor before installing a token, including logout-all. Copy download/execution, staff invitation history/resend/revoke, import job history and unspecified services remain unavailable. `src/lib/data/integrations.ts` records the boundaries.

Access tokens stay in memory. Refresh cookies remain HttpOnly under `/api/v1/auth`, with one refresh in flight and no blanket mutation replay. Auth return links preserve only allowed source/page/conversation/filter context, discard secrets and unknown queries, and retain role checks. Server permission decisions remain authoritative.

Security fixes (22 October 2026): logout-all refreshes expired credentials before revocation and retries only one definite authentication rejection, never an unknown mutation. Unknown login can explicitly reconcile the cookie actor, constrained to the requested username/email; a previous actor cannot be installed. Activation/reset/invitation responses share the credential queue and invalidate prior local session/drafts. Session failures remain visible after local sign-out. Social controls require current class membership/assignment and ACTIVE class; only an author can edit a post, while moderation delete remains distinct.

## One data source, no fallback

`src/lib/data/port.ts` is the frontend port. Only `src/lib/data/index.ts` imports `@data-adapter`. `next.config.mjs` binds that alias to `src/lib/data/live.ts` for live builds, or `dev/mocks/adapter.ts` for explicit development preview. TypeScript checks both against the same port through an ambient declaration; tsconfig must not map this alias to a concrete adapter, because that overrides runtime selection. Preview compiles into `.next-preview`; live uses `.next` to keep artifacts separate. Product pages never import fixtures and never call fetch directly.

`NEXT_PUBLIC_DATA_MODE` accepts only `live` or `mock`; missing means live. Mock is rejected for production build and start. There is no per-feature override, query/localStorage toggle, catch-to-fixture branch or hybrid mode. Fixture data lives exclusively in `dev/mocks`; mocks are excluded from the live dependency graph. `npm run check:boundaries` checks imports/network/storage. `npm run check:release` scans `.next/static` and `.next/server` for the fixture canary; run `npm run build` for the complete release gate. These controls reduce regressions; they do not replace review of newly added code/data sources.

All sample business identities, file rows and counts belong to the development fixture module. Product navigation/labels/static UI copy are not mock data. Build with live configuration after any preview run; never ship a dev server or bypass the build gate.

## Backend boundary

The browser uses same-origin `/api/v1`. The Next route handler forwards only the approved **63-operation** allowlist, including PUT/DELETE and validated nested UUIDs. Query keys are operation-specific; `X-Admin-Reason` only accepts approved enums on relevant mutations. It reads `CORE_API_URL` on the server, preserves cookies, Origin and correlation/retry metadata, refuses external redirects and never forwards service keys or generic idempotency headers. Configure `WEB_ORIGIN` to the exact browser-facing scheme/host/port; mutations must match it. Missing/invalid origin configuration fails closed. Configure Core CORS for that browser origin, not `http://core:8000`. Use HTTPS/secure cookies in a real deployment. The eight new read contracts are documented in Core API_CONTRACT; business permissions and DB schema are unchanged.

Live startup now uses `server.mjs` to overwrite untrusted forwarded/context headers with a signed TCP-peer context. The route verifies `CORE_PROXY_SECRET`, method/path and age before forwarding it; Core verifies independently for rate limiting. The key is distinct from JWT/service keys, required in both server environments and never public. Raw X-Forwarded-For is ignored. An added ingress/load balancer requires a separate trust review; the current listener attests its actual socket peer. Proxy-generated errors now also include a UUID correlation ID in body/header. The security transport contract is documented in Core API_CONTRACT; business operation allowlists remain unchanged.

The user's follow-up authorized the concrete [eight read endpoints](CORE_MISSING_READS_PROPOSAL_2026-10-22.md), followed by explicit AGY permission for one management presentation file. Codex owns actor/session guards, API/controller logic and acceptance. Account status/roles save separately and re-read authoritative state. Whole roster replacement preserves unseen current IDs until explicit removal. MANUAL→AUTO uses actual preview versions; AUTO sync uses the current server roster, since its existing contract has no version preconditions. Draft navigation, one-time code disclosure, unknown mutations and failed post-write reloads are guarded. Preview revision/classification/executor/job/mapping fields are not fabricated. Social role labels are omitted when absent; metadata Admin reads do not grant Social access. Calendar retains timezone instants and multi-day spans. Notifications supply no raw HTML/navigation. Import retains its deliberate same-preview/reason reconfirmation, with no automatic replay.

For each future capability:

1. Approve its public contract and current permission/ownership rules in the owning service. Obtain real OpenAPI/request/response/error examples without secrets.
2. Add the operation/decoder and narrowly scoped proxy destination (or approved API entry design). Keep transport in `lib/api`, never service credentials in client code.
3. Implement the live capability adapter and feature UI states; remove the explicit unavailable outcome for that capability. Map wire DTOs into frontend view models, not the reverse.
4. Test the live path against that service, especially 401/403/404/409, timeout/unknown outcome, cancellation, validation, empty and malformed response. No automatic replay of important mutations. Student create/issue-code/activate reject generic Idempotency-Key.
5. Build in live mode; require boundary and release scan passes. Inspect Network: API down must show an error, not a sample row. Record actual operation-level integration evidence.

## Run and verify

From `apps/web`, run `node scripts/dev-mock.mjs --hostname 127.0.0.1 --port 4179` for explicit development preview. Use `npm run dev` for live mode with the documented server environment. Do not deploy the preview server or build with mock mode.

Earlier preview acceptance (22 October 2026): `npm run check` passed boundaries, TypeScript and **226 behavioral tests**. Chrome mock preview smoke checked **71 route IDs** (68 seeded routes plus 3 UI-created resources); focused journeys passed **214 assertions** with selected screens at 1440/768/390/320px. See [FRONTEND_COMPLETION.md](../FRONTEND_COMPLETION.md) for that historical per-route evidence. Earlier integration acceptance was **298 frontend tests**, a production live build/release scan, and **21 HTTP groups** (38 new operations across six groups + seven Notifications + eight auth/security) against isolated Core/PostgreSQL/Web/worker with verified synthetic TLS SMTP. Three Admin views render actual HTTP receipts in the integration script. See [Admin forms](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md). No browser is connected for this run, so it does not certify click/hydration/all-canvas visuals. The earlier full Core suite is separate historical evidence, not a new backend run.

Historical evidence from 20 October 2026: production browser smoke checked 71 mapped URLs and 18 transport/access/failure/UI assertions against an isolated Core contract stub; this is not a real Core deployment.

The external implementation ledger and current evidence live under `D:/app/cnpm/frontend/artifacts/frontend-implementation`. See `COMPLETION.md`, `status.json` and `antigravity/qa/release-final/gates.json`. Journey evidence distinguishes actual browser interactions, unit tests, static route availability and unavailable live integrations. Selected screens were inspected at390/1024/1440; no blanket all104-canvas visual certification is claimed.

## Agent workflow

Read repository `AGENTS.md`, `apps/web/AGENTS.md` and `.agents/skills/lumi-frontend-orchestrator/SKILL.md`. The same skill is installed for Codex. Per the user's instruction, AGY Flash authors bounded UI; Codex owns business logic, adapters, permissions, async state, integration and acceptance. Argon is available for read-only review. The repository Windows bridge preserves multiline/JSX arguments and rejects empty or permission-denied responses. No global model/provider/approval setting was changed.

## Remaining integration work

Core account/classroom administration now uses the approved metadata reads and existing mutations. Unsupported catalog edit/class rename/override, invitation history/resend/revoke, import history and data-copy execution are outside the contract. Document/AI/Learning/Learner Intelligence remain separate services. Unavailable capabilities never fall back to fixtures. External email delivery, deployment and current browser click/hydration journeys require separate evidence; HTTP/render tests do not certify them. Core performance acceptance is recorded separately from short diagnostics. No Business Rule or migration changed.


## Local development compiler

`npm run dev:mock` uses Next.js 15 Turbopack to reduce initial development compilation. Both `turbopack.resolveAlias` and `webpack.resolve.alias` select the same mode-specific `@data-adapter`. The mock runner still forces mock mode and refuses production; the live build command and release scan are unchanged. Output stays in `.next-preview` for mock and `.next` for live.

Stop the current server before changing compilers or restarting after this script update; never run two servers writing the same output directory. `npm run dev:mock:webpack` keeps the previous Webpack runner available for diagnosing bundler-specific issues. Neither compiler eliminates all cold compilation. Warm route GET times measure development server response, not complete click-to-content or backend latency. Keep the dev cache between ordinary restarts; do not delete `.next-preview` as a routine speed-up step.


## Document v1 — 2026-10-23

Người dùng đã duyệt gói TASK-017. Sáu workspace Document hiện contracted/live trên service độc lập và `/api/document/v1`,27 public operations có allowlist riêng; không đổi63 Core API. `document-http`, `document-decoders`, `document-proxy` và `live-document` giữ transport/DTO ngoài feature. Bearer/refresh/actor generation dùng chung Core session, không expose token getter, không gửi cookie/service credential sang Document.

Upload multipart chứa bytes thật và UUID receipt bền vững. Nội dung reader là text trích xuất thật, không HTML hoặc nội dung mẫu. Foreground sync10 giây và focus/online refresh hủy kết quả cũ theo actor/resource/version; lỗi quyền xóa dữ liệu nguồn đang hiển thị. Notes/bookmarks owner-only, quote được backend che, tên nguồn/lớp lịch sử có snapshot. Các mutation mất phản hồi giữ unknown, chỉ xác nhận bằng evidence dương hoặc phát lại đúng request đã giữ theo thao tác chủ động; không tự replay. AGY Flash chỉ tạo UI/CSS/component được giới hạn, Codex giữ logic/session/quyền/API và nghiệm thu.

Xem [báo cáo TASK-017](DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md) cho kết quả chạy thật. Những đoạn pending Document trước ngày này là lịch sử preview; AI/Learning/Learner Intelligence vẫn cần hợp đồng riêng. Không chứng nhận OCR, AI indexing, owner sign-off hoặc KPI tải từ kiểm thử chức năng.
