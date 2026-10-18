# Bàn giao TV4 — backend task 001–015

Ngày tổng hợp: **2026-10-19**. Nhánh bàn giao: **`tv4`**.

**Cập nhật sau merge PR #10:** `main` hiện ở commit `2f7d70a`; full Core chạy lại trên PostgreSQL 16.14/Python 3.12.14 đạt **342 passed, 0 failed, 0 skipped** trong 387.46 giây; Rule evidence xác nhận 342 cases và 0 skipped/failed scenario. [CI PR head `bb7f88d`](https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant/actions/runs/39157402992) đạt `core-tests`, `compose-smoke`, `web-build`; `core-load` được skip theo cấu hình tùy chọn. PR đã merge, nhưng chưa có owner approval, nghiệm thu toàn Core G2, Web E2E hoặc full TP-01.

Backend Core đã có các luồng chính và bằng chứng kiểm thử local; **chưa nghiệm thu
toàn Core G2, full TP-01 hoặc khả năng vận hành production**. Tài liệu này tập hợp
phần đã làm, giới hạn và việc tiếp theo; không thay thế Business Rules/API Contract.

## 1. Phạm vi và nguồn thay đổi

- Nền code trước đợt TV4: commit `6ac2a85`, gồm Common, Identity, Classroom và
  Social (task 001–011). Đây là công việc đã có của các owner, không ghi nhận lại
  thành phần triển khai mới của TV4.
- Đợt TV4 bổ sung Notification, Administration, công cụ migration/seed, kiểm thử
  backend và sửa các lỗi tích hợp phát hiện trong task 012–015.
- Kiến trúc giữ nguyên: một monorepo, năm microservices; Core là một service gồm
  nhiều module. Runtime liên module dùng public interface; không đọc DB service khác.
- Theo phạm vi người dùng chốt, không sửa `apps/web`, không triển khai frontend.
  Các job Web/Compose có sẵn trong CI vẫn được giữ; kết quả backend local không
  chứng nhận các job đó hoặc Web E2E.
- Push nhánh là bàn giao source, không phải deploy hoặc merge vào `main`.

## 2. Trạng thái task 001–015

| Task | Backend hiện có | Giới hạn còn lại |
|---|---|---|
| 001 Common | Config, DB, auth lookup hiện hành, error envelope, audit; thêm outbox và admission gate | Limiter/cache một process; shared changes cần review TV1 và consumers |
| 002 Identity core | Student provision/activate/recovery không email; staff email; login/refresh/revocation; legacy conversion giữ định danh | Mapping dữ liệu legacy thực; SMTP thật và delivery reliability |
| 003 Identity HTTP | Auth/profile/Student API, cookie/CSRF, register bị chặn, secret response no-store, OpenAPI tests | Limiter/idempotency RAM không bền vững khi restart/multi-worker |
| 004 Identity public | DTO, permission helpers, public operations cho Admin/import/data requests; coverage gate 100% | Fulfillment dữ liệu thật cần policy/executor; owner review contract |
| 005 Classroom schema | School, homeroom/roster, subject class, AUTO/MANUAL, TeachingAssignment | `users.school_id` nullable, chưa có FK; mapping legacy chưa duyệt |
| 006 Enrollment/transfer | Admin roster/sync, preview/version confirm, AUTO/MANUAL và transfer giữ lịch sử | Learning transfer cutoff/timed-attempt policy và consumer thực tế |
| 007 Lifecycle/assignment | PRIMARY/ASSISTING, thay giáo viên chính, archive/restore, quyền hiện hành | Learning approval/grading và lifecycle liên service |
| 008 Classroom public/internal | Action access, scope, limited personal history, service credential, fail closed | Source grant của Document, điểm/bài nộp/chat của service chủ quản |
| 009 Feed | Feed CRUD/soft-delete, author DTO, cursor/sort, membership/resource checks, moderation audit/outbox | Review owner; chưa kiểm chứng toàn bộ liên service |
| 010 Comments | Body/parent checks, soft-delete/moderation, audit/outbox | Ghi outbox lỗi rollback transaction; worker delivery lỗi retry sau commit, không đồng nhất hai trường hợp |
| 011 Calendar | Core events, time validation, class access, Learning read-only projection/version handling | Projection tests chưa phải Learning E2E |
| 012 Notification | Inbox/read/read-all, recipient-only, transactional outbox, worker retry/dedup | Review event contracts; không dùng để giao credential SMTP |
| 013 Administration | Staff/status/roles, school audit, CSV/XLSX preview/confirm, data-request review | Thiếu policy/executor giữ IN_REVIEW; SMTP/legacy audit giới hạn bên dưới |
| 014 Migrations/seed | Metadata registry, head 0012, downgrade guard, report/plan/apply manifest, seed dev/test | Dữ liệu thực/mapping/FK và quy trình production onboarding chưa được nghiệm thu |
| 015 Security/integration | HTTP journey, permissions, concurrency, boundaries, evidence, backend runtime/load checks | Client latency cao; full TP-01 và owner approval còn pending. CI PR #10 đã xanh; xem cập nhật đầu tài liệu |

Các checklist/đoạn “hiện trạng” cũ trong task 001–011 là lịch sử và có chỗ chưa
cập nhật theo đợt tích hợp này. Không diễn giải ô chưa tick thành chắc chắn thiếu
code, cũng không tự tick acceptance liên service chỉ vì Core tests đạt.

## 3. Chi tiết phần TV4 bổ sung

### Task 012 — Notification

- Migration mới `0011`; inbox list/read/read-all chỉ cho recipient hiện hành.
- Producer Classroom/Social ghi outbox cùng transaction nghiệp vụ, snapshot audience
  và payload có kiểu, chỉ chứa thông tin được phép; không chứa mật khẩu/mã kích hoạt.
- Worker dùng SKIP LOCKED, retry/backoff theo DB clock, dedup; fanout và đánh dấu
  published cùng transaction. Compose có `notification-worker` sau migration.
- 31 test Notification; mốc kiểm thử lịch sử toàn Core khi hoàn thành: 251 test đạt.

### Task 013 — Administration

- Staff invitations, status/role mutation, thu hồi phiên; bảo vệ Admin cuối cùng
  còn sử dụng được bằng transaction/advisory lock.
- Audit theo school scope, allowlist payload; giữ nguyên audit legacy có scope null,
  không đoán trường để backfill hoặc hiển thị chéo scope.
- Import Student CSV/XLSX: tối đa 100 dòng/2 MB, kiểm tra archive/XML; preview 30 phút
  gắn actor/trường/fingerprint/roster version. Confirm atomic qua public interfaces,
  gồm account, roster tùy chọn, AUTO sync, audit/outbox.
- Kết quả confirm lưu bền vững; mã chỉ trả ở lần tạo đầu tiên. Replay trả cùng user
  IDs và code null, không reset thông tin xác thực khi re-import.
- Bốn loại ACCESS/EXPORT/CORRECTION/DELETE có list/detail/review/reject/defer.
  Theo chỉ đạo người dùng: **giữ IN_REVIEW khi chưa đủ điều kiện**, không ghi
  COMPLETED nếu chưa thực hiện thành công hành động dữ liệu tương ứng.
- Migration mới `0012`; 38 test Administration; mốc lịch sử toàn Core: 290 test đạt.

### Task 014 — Migration, maintenance và seed

- Registry nạp model của các module đã triển khai; không tạo migration placeholder
  hoặc sửa migration cũ đã áp dụng. Một Alembic head: `0012`.
- CLI report và School manifest plan/apply có SHA approval gắn DB/revision/trạng
  thái hiện hành; apply khóa/recheck, từ chối remap chéo trường và xung đột lịch sử.
  Giữ UUID/hash/status/history, không tự kích hoạt hoặc mở LOCKED; đổi scope thu hồi phiên.
- Downgrade guard preflight trước DDL, chặn mất dữ liệu feature/scope/envelope;
  offline downgrade bị từ chối. Hướng dẫn trong [runbook](../services/core/migrations/README.md).
- Seed chỉ dành cho DB dev/test riêng, có expected-name/empty preflight, transaction,
  durable marker và concurrency guard. Mật khẩu Admin do operator truyền môi trường;
  không in credential. Seed có 7 homeroom khối 6–12, 14 lớp AUTO/MANUAL và assignments.
- 23 maintenance tests; mốc lịch sử toàn Core: 313 test đạt PostgreSQL 16.

### Task 015 — Kiểm chứng và sửa lỗi tích hợp

- HTTP journey thực từ login/provision/activation/enrollment đến feed/comment/calendar,
  worker notification, audit, transfer, limited history, archive/restore và revocation.
- Kiểm tra role/status/school hiện hành so với JWT đã phát hành; parent/resource,
  cross-school, membership bị thu hồi và Identity outage fail closed.
- 300 thao tác cạnh tranh: 100 sync/roster, 100 transfer retries và 100 import confirms,
  16 workers mỗi scenario; đối soát history/uniqueness và toàn bộ MANUAL membership.
- Sửa cached replay Classroom chỉ kiểm tra Admin role: nay kiểm tra lại scope của
  source/destination/created resources, kể cả response 204, trước khi trả cache.
- Sửa thiếu public import boundary cho mutation helper; AST guard kiểm tra static
  imports/SQL literals, không chứng minh mọi dynamic import/SQL đều an toàn.
- Thêm ASGI admission trước sync dependencies để giới hạn request theo DB pool,
  giữ permit qua dependency cleanup; timeout trả no-store 503/Retry-After. Health
  không bị gate. Pool cấu hình qua môi trường, mặc định vẫn 5 + 10 overflow.
- Rule catalog nối scenario với JUnit; missing/skip/failure không được tính đạt.
  CI xuất artifacts, có workflow_dispatch tùy chọn đo tải 10 phút. Nhánh `tv4`
  được thêm vào push trigger; tại thời điểm bàn giao, remote CI chưa chạy.

## 4. Bằng chứng kiểm thử đã chạy

Các số liệu bảng dưới đây là kết quả local tại thời điểm chạy; CI PR #10 được bổ sung trong cập nhật đầu tài liệu.

| Kiểm tra | Kết quả |
|---|---|
| Full Core suite | **342 passed, 0 failed, 0 skipped**, PostgreSQL 16.14, Python 3.12.14, 651,17 giây |
| Coverage | Line **93,51%**, branch **78,28%**, combined **90,80%** (làm tròn 91%) |
| Identity public gate | 17 tests, **100% line/branch** trong module này |
| Concurrency bổ sung | 3 tests đạt sau khi tăng đối soát MANUAL; 300 thao tác, 39,37 giây |
| Lint/format | Ruff đạt; 139 files đã kiểm tra format tại mốc task 015 |
| CI PR #10 | `core-tests`, `compose-smoke`, `web-build` đạt tại head `bb7f88d`; `core-load` skipped |
| Runtime backend | Compose sạch: DB/migrate/Core/worker; wheel site-packages, UID 10001, no schema drift |
| Health | DB down: ready 503/live 200; DB restart: ready hồi phục |
| Scope | Không build/start Web trong lần smoke local; không dùng dữ liệu người dùng thật |

Hai delivery tests từng thất bại khi full suite chạy đồng thời với load; đã đặt rõ
fixture event chưa attempt phải đến hạn trước single drain, giữ nguyên tests kiểm
tra schedule/retry và production worker/clock. Full suite sau đó đạt như trên;
không khẳng định đã xác định nguyên nhân clock từ lần lỗi ban đầu.

Artifacts tổng hợp không chứa credential:
[verification](../services/core/test-evidence/task015/verification.json),
[rule results](../services/core/test-evidence/task015/rule-results.json),
[runtime](../services/core/test-evidence/task015/runtime.json),
[load](../services/core/test-evidence/task015/core-load-2026-10-19.json).
Branch/workspace metadata trong artifacts phản ánh thời điểm đo trước commit/push,
không phải trạng thái Git hiện tại. Command tái lập tại [tests README](../services/core/tests/README.md).

### Đo tải: đạt ngưỡng backend trong phạm vi hẹp, còn vấn đề đầu cuối

- Một Uvicorn worker + PostgreSQL Docker loopback; 100 closed-loop users, 10 lớp,
  500 Students, warmup 30 giây + đo 600 giây; pool profile 15 + 0 overflow.
- 11.416 requests: 11.415 HTTP 200, 1 transport/contract error; success **99,9912%**,
  không quan sát response sai scope. Khoảng 19 requests/giây; 100 users không có
  nghĩa là đã chứng minh 100 requests/giây.
- Backend ASGI p95 **96,51 ms**, nhưng client p95 **15,58 giây**, max **45,72 giây**.
- Máy Windows dùng chung tài nguyên với một phần tests/build, không có resource
  isolation. Chưa xác định bottleneck transport/client/server; cần đo lại và phân tích.
- Chưa có mixed-service fixtures Document/Learning/AI/Intelligence.
  `full_tp01_verified=false`, `full_core_g2_verified=false`.

## 5. Vấn đề còn mở và hướng xử lý

| Mã | Vấn đề / ảnh hưởng | Bước tiếp theo / owner phối hợp |
|---|---|---|
| OPEN-01 | Follow-up không chạy suite/build đồng thời ghi backend p95 18,79 ms, client p95 1,17 giây (max 9,99 giây), trong khi lượt trước là 15,58 giây; chênh lệch chưa rõ nguyên nhân và chưa đủ bằng chứng user-facing SLO | TV4 đo lại trên môi trường cô lập, giữ cả backend/client metrics và phân tích bottleneck trước khi nghiệm thu TP-01 |
| OPEN-02 | Legacy School mapping chưa duyệt, users.school_id nullable/chưa FK | TV1/TV2 duyệt manifest dữ liệu thực; provision School trước Identity, plan/apply theo runbook rồi migration constraint mới khi đủ điều kiện |
| OPEN-03 | Limiter/non-import idempotency cache process-local | TV1/TV2/TV4 chốt yêu cầu multi-worker/restart, thiết kế cơ chế dùng chung/bền vững; không suy ra durable semantics từ import |
| OPEN-04 | SMTP trước DB commit có thể gửi invite không dùng được nếu commit lỗi; chưa test provider thật | TV1/TV4 chốt delivery/reissue/retry có bảo vệ credential; thử SMTP thật khi có cấu hình, không đưa mã vào inbox/outbox chung |
| OPEN-05 | Data requests chưa có fulfillment/retention và quy trình xác minh thực tế | Operator/owner duyệt policy và executor theo từng service; tiếp tục IN_REVIEW khi thiếu điều kiện, không tự xóa/export liên service |
| OPEN-06 | Learning/Document/AI/Intelligence chưa có triển khai để E2E | Chốt owner/contracts trước task 017–020; test transfer attempt, grants/revoke, grading/approval và private history tại service chủ quản |
| OPEN-07 | Audit legacy school null không hiện trong scoped Admin API | Giữ nguyên dữ liệu; nếu cần phân loại, dùng phương án mapping riêng có bằng chứng/approval, không đoán school hoặc nới quyền |
| OPEN-08 | Seed chỉ dev/test, không phải production first-Admin bootstrap/onboarding | Operator/TV1/TV2/TV4 cần chốt runbook production riêng trước rollout; không bỏ guard seed |
| OPEN-09 | Một số task 001–011 còn checklist/nhận định lịch sử | Owner đồng bộ với code/evidence này, phân biệt phần Core đã test và acceptance liên service còn pending |
| OPEN-10 | Shared/API/schema thay đổi chưa có owner approval; CI PR #10 đã xanh tại head `bb7f88d` | TV1 review auth/public/audit, TV2 review Classroom/mapping, TV3 review Social/events, TV4 review worker/Admin/infra; không coi CI thay owner review |
| OPEN-11 | Bộ test hữu hạn, overall branch coverage 78,28%; AST guard có giới hạn | Bổ sung test theo lỗi/rủi ro phát hiện và review thực tế; không tuyên bố không còn bug hoặc bảo đảm tuyệt đối từ coverage |

Ưu tiên: OPEN-01 và owner review trên đúng commit; sau đó chốt mapping/onboarding,
delivery/idempotency theo cách triển khai dự kiến. Phần thiếu policy/service vẫn
được ghi pending. Frontend không nằm trong phạm vi đợt backend này.

## 6. Review và triển khai

- Migration mới duy nhất của đợt này: `0011`, `0012`. Đọc runbook, backup và kiểm tra
  report/plan trước khi chạm dữ liệu thực; không dùng kết quả trên DB tổng hợp để
  tự áp manifest thực hoặc downgrade dữ liệu có feature.
- Các file shared cần review: `common/`, `bootstrap.py`, `main.py`, public interfaces,
  migration environment/model registry, dependencies, Compose, CI và API contract.
- Cấu hình thật theo `.env.example`; không commit `.env`, DSN/token/mật khẩu thật.
  Tại thời điểm bàn giao ban đầu chưa có merge/deploy; PR #10 sau đó đã squash-merge vào `main`.
  Không force-push hoặc gửi thông báo cho owner.
- Tài liệu chi tiết: [Core README](../services/core/README.md),
  [API Contract](../docs/architect/microservices-v1/core/API_CONTRACT.md),
  [task 012](TASK-012-notification-module.md), [task 013](TASK-013-administration-audit.md),
  [task 014](TASK-014-core-migrations-db.md), [task 015](TASK-015-core-integration-security-tests.md).
