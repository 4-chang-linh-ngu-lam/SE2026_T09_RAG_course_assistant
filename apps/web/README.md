# Lumi Web

Bắt đầu từ [hướng dẫn mã nguồn/chạy/trải nghiệm Core–Document](../../docs/LOCAL_DEVELOPMENT.md). Bản fullstack đã có 63 Core + 27 Document operations; xem [nghiệm thu TASK-017](docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md) cho bằng chứng mới nhất. Các số liệu bên dưới ghi riêng từng mốc lịch sử.

Class feed/notifications follow-up: [UI, synchronization and worker checks](docs/CORE_CLASS_FEED_NOTIFICATIONS_2026-10-23.md), verified with 338 Web tests, 9 new backend regressions, 22 HTTP groups and 7 real Chrome groups. Feed drafts survive foreground refresh; the shared inbox drives the bell and center, with safe links to existing class/post/comment routes.

Latest login/email integration: [role-specific activation and emailed onboarding links](docs/CORE_EMAIL_LINK_FLOW_2026-10-23.md), verified with 329 Web tests, 51 focused backend tests and 22 HTTP/six real Chrome groups.

For a reproducible local live demo, public **development-only** Admin credentials and the full Admin/Student/Teacher test walkthrough, start with the [repository README](../../README.md#core-web-demo). Its separate demo stack uses Web port 3100; existing local accounts on 3000 keep their own credentials.

Current functional Web–Core work: [connection fixes, 23 October 2026](docs/CORE_WEB_CONNECTION_FIXES_2026-10-23.md). Earlier implementation evidence: [Core completion report](docs/CORE_COMPLETION_2026-10-23.md). Performance optimization is deferred under the current scope.

Next.js frontend scaffold in the product monorepo. Route/layout coverage is not completion of the 104 designs. Feature ownership and unimplemented integrations are explicit in `docs/FRONTEND.md` and `src/lib/data/integrations.ts`.

Requires Node 22.17+ and npm. From `apps/web`:

```powershell
npm ci
if (!(Test-Path .env.local)) { Copy-Item .env.example .env.local }
npm run dev
```

Live is the default. Set server-only `CORE_API_URL` and `WEB_ORIGIN` in `.env.local`; browser requests use same-origin `/api/v1`. `WEB_ORIGIN` is the exact public web scheme/host/port, even behind Docker or a reverse proxy; set it in Core too so email links open the correct environment. Set Core `CORS_ORIGINS` to that same public origin and configure cookie security appropriately. No internal service credential belongs in the web app.

Login keeps the Student activation link only on the Student tab, with an explicit Student label. Staff invitations open `/staff/invitation#token=...` from email, while staff recovery opens `/reset-password#token=...`. Both consume the fragment into memory, remove it from the address bar, and submit only when the user chooses a new password. Opening a link alone does not activate an account. Existing query-token links remain accepted; Student activation remains the separate Admin-issued username/code workflow.

Live `dev`/`start` run `server.mjs`, which attests the actual TCP client address for Core rate limiting. Configure a distinct random `CORE_PROXY_SECRET` (32+ characters), with the same value in Core/root `.env` and Web `.env.local`. It is server-only and must not reuse the JWT or internal service key. Use `npm.cmd run dev` on Windows; direct `next dev`/`next start` bypass the listener and authenticated proxy requests fail closed. Mock preview still uses its isolated runner. If placing an ingress proxy in front of Node, review client-IP trust at that boundary; arbitrary forwarded headers remain untrusted.

For Turbopack development, use `npm.cmd run dev -- --turbopack`. Both bundlers share the live adapter boundary.

For an isolated UI preview: `npm run dev:mock`. Preview accounts and data exist only in `dev/mocks/fixtures.ts`; Student username `minh.anh10a1`, staff `ha.nguyen@lumi.example` / `nam.pham@lumi.example`. Enter any nonempty password in this development-only adapter. The preview banner is always shown; no email/file/grade/backend persistence occurs. Refreshing a tab loses the in-memory preview session.

```powershell
npm run check
npm run build
npm start
```

The production build and server reject mock mode. The live build selects the live adapter at compilation, checks product import boundaries, then scans served bundles for the fixture marker. Missing APIs, invalid responses and errors never return fixture data. See `docs/FRONTEND.md` for integration steps and limitations.

Live Core exposes **63 approved operations** through the scoped proxy, including the eight metadata reads authorized to complete Core. Account lists/details, academic catalog, homeroom roster/transfer, class creation, teacher assignments, enrollment and archive/restore use actual server data and supported mutations. Identity, Notifications, feed/comments (including author-only comment editing), calendars, audit, staff invite, original-file import and data-request review remain live. Unsupported mutations/executors never use preview fields or fixtures. See [the API matrix](docs/CORE_API_MATRIX_2026-10-22.md) and [read contract](docs/CORE_MISSING_READS_PROPOSAL_2026-10-22.md). `docker compose up -d db migrate core notification-worker` runs the worker required for inbox delivery.

Run the real, disposable Web–Core integration suite from `apps/web`:

```powershell
npm.cmd run test:core
```

To include real Chrome interaction against the same isolated fixture on Windows:

```powershell
$env:CORE_BROWSER_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
npm.cmd run test:core
Remove-Item Env:\CORE_BROWSER_EXECUTABLE
```

This adds seven browser groups: Admin course creation; role-specific login links and emailed staff invitation activation/replay; Student class/feed/comment/session journeys; offline unknown-outcome reconciliation and a forbidden route; two-actor feed/notification synchronization; Teacher calendar editing; and account locking/revocation. The runner creates a separate headless browser profile and removes it plus its synthetic credential handoff file in cleanup. Screenshots and aggregate results remain in the private temporary artifact directory. No browser package is installed. Without this environment variable, the command continues to verify HTTP/render behavior only.

Requires Docker Desktop/Compose, Node 22.17+ and the existing Web dependencies. The command builds production Core/Web/worker, allocates separate loopback ports, creates a fresh PostgreSQL volume and random test credentials, seeds synthetic accounts, runs **seven HTTP groups covering all 46 Classroom/Social/Calendar/Administration operations**, seven Notifications and eight Identity/security groups, renders ten management routes plus three Admin forms from real HTTP state, and verifies DB outage/recovery. It uses its own Core image tag and Compose project; development services/data are not stopped or reused. No operational URL or credentials are accepted. Inherited SMTP settings are removed; a private SMTPS sink with a temporary CA verifies the real Core email sender and staff invitation acceptance without forwarding mail externally or disabling certificate verification.

Cleanup runs on failure as well as success. Test containers/network/volume, the generated credential file, TLS key/certificate and mail spool are removed; private logs plus aggregate `summary.json` remain in the printed temporary directory for diagnosis. Errors print phase/type rather than assertion payloads or tokens. This suite verifies HTTP/DB and synthetic TLS email integration, plus browser interaction when explicitly enabled above. External email delivery and AI/Learning/Learner Intelligence have separate verification requirements; enable the Document extension below for its live checks. Frontend checks and the full backend suite remain separate gates; the Docker Web build runs the live build and fixture-canary release gate.


## Document live (TASK-017)

Sáu màn Document đã dùng service độc lập: thư viện và nguồn giáo viên, tài liệu lớp giáo viên/học sinh, Reader, ghi chú/bookmark riêng. Cấu hình server-only `DOCUMENT_API_URL` (`http://127.0.0.1:8200` khi native, `http://document:8200` khi Compose). Namespace `/api/document/v1` có allowlist 27 operations, kiểm tra origin/listener attestation và dùng chung session Core; không chuyển cookie hoặc service key sang Document.

Xem [khởi động và luồng trải nghiệm](../../services/document/README.md), [hợp đồng](../../docs/architect/microservices-v1/document/API_CONTRACT.md) và [bằng chứng kiểm thử](docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md). Thêm `$env:CORE_DOCUMENT_TEST='1'` trước `npm run test:core` để build/test thêm Document trong fixture độc lập. Với `CORE_BROWSER_EXECUTABLE`, runner kiểm tra cả thao tác UI Document và Core. Script tạo và dọn tài khoản/tệp/DB/volume/profile tổng hợp riêng; không dùng Gmail hoặc DB của người dùng.

READY nghĩa trích xuất text thành công; AI indexing/tutor vẫn thuộc TASK-018. Không fallback fixture khi service lỗi. Reader hỗ trợ tải bản gốc, ghi chú đúng phiên bản/vị trí, chọn trích dẫn, đồng bộ khi có quyền thay đổi và che quote tại backend khi mất quyền.
