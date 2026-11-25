# CORE-00 — Khảo sát kỹ thuật Core

**Trạng thái:** CORE-00 — DISCOVERY APPROVED, CLOSED — DOCUMENTATION PENDING COMMIT
**Phạm vi:** discovery-only. Không sửa application code, schema hoặc migration; không bắt đầu CORE-01.
**Baseline tối thiểu:** commit 27f5f6371d246f027ae4f501c083e125b7cb1961.

## 1. Git safety và nguồn bằng chứng

| Mục | Kết quả |
|---|---|
| Repository/worktree | D:/Workplace/SE2026_T09_RAG_course_assistant |
| Branch / HEAD | codex/rag-technical-discovery / 27f5f6371d246f027ae4f501c083e125b7cb1961 |
| origin branch | origin/codex/rag-technical-discovery cùng HEAD |
| Pull | Fetch và pull --ff-only hoàn tất; remote up-to-date, không diverge |
| Local files | Giữ nguyên docs/problem/ và stitch-rag-consistency.zip; không stage hay sửa |
| DOC-00 baseline | Đã đọc 11 tài liệu docs/architect/document-discovery/00–10; dùng lại bằng chứng hiện có, chỉ bổ sung Core-specific trace |

Thiết kế mới được đối chiếu: CORE-D01–08/CORE-T01–08, LRN-D01–10/LRN-T01–10, NTF-D01–05/NTF-T01–05, SYS-D01–05/SYS-T01–07 và Master Implementation Plan. Design accepted là target, không phải bằng chứng implementation đã hoàn tất. Business Rules vẫn là nguồn nghiệp vụ ưu tiên.

## 2. Kết luận điều hành

Core không cần viết lại. Code hiện có FastAPI composition root, Identity, Classroom/Admin, Social, Notification module/worker, Administration, health, PostgreSQL/Alembic đến migration 0014 và test theo module. Core API Contract đánh dấu các module này IMPLEMENTED: docs/architect/microservices-v1/core/API_CONTRACT.md:3.

Khoảng trống mở đường cho Document/Learning/AI:

1. Authorization có logic dùng được, nhưng HTTP interface là legacy GET theo lớp và X-Service-Key; CORE-T03 yêu cầu POST tổng quát, action registry và Service JWT.
2. Service JWT thuộc foundation chung SYS-02/CORE-T04. Không tạo JWT issuer/key system riêng trong Core hoặc Document.
3. Notification hiện chạy trong Core, cùng schema/outbox và worker. Có thể tái sử dụng hành vi và test vector, nhưng không bê nguyên model/repository sang Notification Service.
4. Account deletion phân tán/per-target completion là design target mới; chưa có job/event/retention cleanup tương ứng trong application code.
5. CORE-D04 về join code/lời mời và owner transfer xung đột với Business Rules/API Contract hiện hành. Không implement các flow đó trước khi Technical Lead xử lý xung đột.

## 3. Luồng Authorization hiện tại

### User access token

1. Identity ký access JWT bằng SECRET_KEY; thuật toán cấu hình hiện tại là HS256. Claims gồm user ID, roles, session version, issued-at và expiry: services/core/app/common/security.py:44–70; app/common/config.py:18–21.
2. get_current_user xác minh chữ ký/expiry, tra user hiện hành, rồi yêu cầu ACTIVE và session_version khớp. Role trong token không thay thế role DB hiện hành: app/common/auth_dependencies.py:48–83.
3. Role/school permissions được kiểm tra ở dependency/service trước nghiệp vụ.

### Service request hiện tại

1. Caller gửi header X-Service-Key.
2. verify_internal_service_key so sánh constant-time với INTERNAL_SERVICE_SECRET; chưa cấu hình trả 503, sai key trả 401, đúng key luôn nhận scope core:check_access: app/common/auth_dependencies.py:86–96; config.py:26.
3. Route là GET /internal/v1/classes/{class_id}/access với user_id/action; router kiểm tra scope rồi gọi check_class_action: app/modules/classroom/router.py:482–493.
4. Tại snapshot CORE-00 ban đầu chưa có Service JWT verifier hoặc generic POST authorization/check. SYS-02 utility đã được thêm sau đó; legacy route và CORE-T03 POST/action registry migration vẫn chưa có.

### Logic Core có thể tái sử dụng

check_class_action tại app/modules/classroom/public.py:113–174 kiểm tra user ACTIVE và có school scope, class cùng trường, role hiện hành, membership/teaching assignment và policy theo action. Hàm có tùy chọn FOR SHARE để giảm race với mutation lớp. Hàm được xuất qua classroom.public và được dùng bởi permission checks/tests.

Đây là logic có thể giữ lại phía Core sau adapter; không phải API để service khác import hoặc truy vấn Core DB. Document vẫn kiểm tra ownership/grant/version. CORE-T03 target yêu cầu POST REST contract; không sửa Core logic trước khi action semantics được thống nhất.

## 4. Mapping action hiện tại sang CORE-T03

CORE-T03 target nhận user_id, resource_type, resource_id, action và trả allowed. Core xác minh user/membership/role; service sở hữu tài nguyên kiểm tra permission bổ sung. Mapping dưới đây là ứng viên tương thích, chưa phải policy mới.

| ClassAccessAction hiện tại | CORE-T03 action gần nhất | Phần có thể tái sử dụng | Phần không được suy ra |
|---|---|---|---|
| READ_DOCUMENT_SOURCE | DOCUMENT_READ | Class membership/teacher assignment và cùng trường | Không chứng minh Document grant, owner, active version hay quyền tải source |
| USE_AI_TUTOR | AI_QUERY | Current code yêu cầu lớp ACTIVE và current Student | Không tự mở cho Teacher/ngoài lớp; role policy cần xác nhận |
| PARTICIPATE_CURRENT_CLASS | PRACTICE_ACCESS / ASSIGNMENT_SUBMIT | Class ACTIVE và current Student/Teacher | Learning còn kiểm assignment, attempt, deadline và ownership |
| GRADE_SUBMITTED_WORK | GRADE_MANAGE | Class ACTIVE và current Teacher | Learning còn kiểm submission/assignment được phân công |
| MANAGE_CLASS_CALENDAR | Không có mapping trực tiếp | Có predicate current Teacher và class ACTIVE | Không đồng nghĩa DOCUMENT_SHARE hoặc ASSESSMENT_MANAGE |
| READ_CLASS_CONTENT | Không có mapping trực tiếp | Current member/teacher read gate | Không thay DOCUMENT_READ vì thiếu grant/source check |
| MODERATE_CLASS_CONTENT | Không có mapping trực tiếp | Current Teacher/Admin trong lớp ACTIVE | Admin moderation không cấp quyền quản lý source/grant |
| READ_OWN_HISTORY | Không có mapping trực tiếp | Lịch sử membership của chính Student | Không cấp quyền nguồn hiện tại hoặc nguồn đã revoke |

CORE-T03 còn có DOCUMENT_SHARE, DOCUMENT_MANAGE, ASSIGNMENT_CREATE, ASSESSMENT_MANAGE, ANALYTICS_VIEW nhưng chưa có action tương đương rõ trong enum hiện tại. Không ép map sang action “gần giống”. DOCUMENT_MANAGE phải kết hợp owner policy ở Document; DOCUMENT_SHARE cần role/action policy theo Business Rules.

**Adapter target:** consumer gọi CORE-T03 qua REST bằng Service JWT dùng chung; Core là nguồn user/class role/membership; Document/Learning kiểm tra resource-local permission. Không import app.modules.classroom.repository hoặc truy vấn bảng core.*. Candidate resource type/action mapping cần chốt trước khi freeze OpenAPI.

## 5. Service JWT và migration

| Thành phần | Hiện trạng | Target |
|---|---|---|
| User access token | HS256, SECRET_KEY, 15 phút mặc định; DB lookup kiểm tra status/session version | Giữ auth hiện có, không viết lại |
| Refresh token | Token ngẫu nhiên, hash trong Identity; rotation/revoke qua DB | Giữ Identity/session flow hiện tại |
| Internal service identity | Shared `lumi-service-auth` RS256 signer/verifier and Core FastAPI dependency exist locally; current legacy GET still uses X-Service-Key. | SYS-02 contract/package exists; key provisioning and CORE-T03 route/consumer migration remain pending |
| Authorization transport | GET class-scoped legacy route | CORE-T03 POST resource/action contract |
| Key lifecycle | SYS-02 có signer chọn `kid`, verifier tra trust map cho nhiều key; chưa cấu hình key vận hành | Foundation cấp hệ thống; provisioning, distribution và rotation runbook còn pending |

Không thay User JWT bằng Service JWT và không tạo key lifecycle riêng cho Document. Chuyển đổi cần shared foundation và rollout consumer/endpoint theo contract; compatibility window/dual acceptance phải do Technical Lead quyết định. SYS-02 signer/verifier và dependency có unit-test local; việc cấu hình khóa trên môi trường, triển khai CORE-T03 và migrate consumer chưa được chứng minh.

## 6. Core đã có — tránh rewrite

| Area | Bằng chứng | CORE-00 disposition |
|---|---|---|
| CORE-T01 database | Schema core, SQLAlchemy/Alembic, migrations 0001–0014; README nêu migration head 0014 | Reuse; không tạo baseline mới. Migration thêm chỉ khi gap được duyệt |
| CORE-T02 public API | Identity, Classroom/Admin, Social, Notification, Administration có router/API contract/test | Reuse DTO/error/API conventions |
| CORE-T03 authorization | check_class_action + GET access route hiện có; generic POST/action registry chưa có | Adapt transport/action registry, giữ logic Core khi mapping được kiểm chứng |
| CORE-T04 auth | User JWT/refresh/session/current role checks exist; SYS-02 shared package and Core adapter are implemented locally. | No user auth rewrite; key provisioning/rotation and consumer adoption remain |
| CORE-T05 transactions | Core mutations có transaction boundaries; Feed/Notification dùng outbox | Reuse pattern; không gọi service khác trong DB transaction |
| CORE-T06 outbox | common.outbox và event envelope v2 tồn tại; Notification worker xử lý local trong Core DB | Reuse semantics, cần per-target REST delivery khi tách NTF |
| CORE-T07 resilience | Outbox worker có SKIP LOCKED, retry/backoff; Core admission/auth controls có | Reuse pattern, nhưng không coi là service JWT hay Notification inbox riêng |
| CORE-T08 deletion | Không thấy DELETION_PENDING, account_deletion_jobs hay user.deletion_requested trong app/migrations; DELETE data-request hiện là yêu cầu thủ công PENDING | Missing/blocked bởi retention, owner và completion contract |

### Business-rule/design conflict

- Business Rules A6/A8 và Core API Contract nói không có join code/self-join; chỉ Admin tạo lớp và quản lý roster. CORE-D04 lại ghi join bằng mã/lời mời. Business Rules/API Contract ưu tiên; chưa implement invite/join.
- H1 quy định Admin thay PRIMARY/ASSISTING và không có teacher owner-transfer. CORE-D03/D04 thêm OWNER/TEACHER và transfer owner; phải map/điều chỉnh design, không thêm role hoặc flow mới trong CORE-00.
- C-AC01 “register hợp lệ” không hợp với register hiện bị BLOCKED — LEGACY. Acceptance nên xác minh register bị chặn và Admin provisioning thay thế, sau khi owner cập nhật design.

## 7. Notification: module trong Core, chưa phải service

### Hiện trạng

- app/bootstrap.py:14–23 đăng ký Notification router trong Core FastAPI.
- Public routes dưới /api/v1/notifications dùng Core get_current_user; không có Notification internal POST /events trong code.
- Notification model kế thừa Core Base, bảng thuộc schema core và FK tới core.users.id: modules/notification/models.py:11–13.
- Worker dùng Core SessionLocal và app.common.outbox.OutboxEvent; drain_outbox lock SKIP LOCKED, tạo notification và đánh dấu published trong cùng Core DB transaction: modules/notification/worker.py:21–76; common/outbox.py:20–79.
- events.prepare_delivery import Classroom/Identity/Social public APIs để resolve recipient, kiểm trường/quyền và redact payload: modules/notification/events.py:11–19, 79–140.
- app.background_worker.run_batch chạy cả notification outbox lẫn credential delivery của Identity; Compose notification-worker dùng Core image/DB. Worker notification standalone vẫn phụ thuộc Core SessionLocal.

### Khả năng tái sử dụng khi tách NTF

Có thể reuse hành vi/schema validation, allowlist/redaction, recipient dedup, retry/backoff, pagination/read semantics và PostgreSQL test cases làm tài liệu/test vectors. Không bê nguyên ORM/repository/worker: FK Core user, Core Base/SessionLocal và imports Core nội bộ vi phạm service DB ownership.

NTF cần database/credential riêng, durable inbox + POST /internal/v1/events theo NTF-T03, shared Service JWT, recipient lookup qua public contract, per-target event ACK. Core giữ outbox producer; Notification ACK 202 chỉ là nhận bền vững, không có nghĩa delivery hoặc account deletion hoàn tất. Identity credential delivery vẫn thuộc Core.Identity.

## 8. CORE acceptance matrix — bằng chứng hiện trạng

| AC | Bằng chứng / trạng thái |
|---|---|
| C-AC01 register | Public register trả 403 theo Business Rules; acceptance “register hợp lệ” là conflict cần sửa trong design. |
| C-AC02–03 login/refresh | Identity JWT/refresh/session code và tests có; targeted local tests pass. |
| C-AC04 suspend/delete pending | Status/session_version hiện hành được kiểm tra; distributed DELETION_PENDING không có trong code. PARTIAL. |
| C-AC05 class có đúng owner | Current API tạo lớp và PRIMARY lecturer; CORE design OWNER role chưa map. PARTIAL/DOMAIN MAPPING OPEN. |
| C-AC06 join/invite | No join code/self-join là rule; Core D04 acceptance invite conflict. |
| C-AC07 transfer owner | Không có current owner-transfer API; H1 phân công teacher do Admin. CONFLICT/NOT IMPLEMENTED. |
| C-AC08 remove member revoke downstream | Core current membership check có; Document/Learning/AI E2E chưa có. PARTIAL. |
| C-AC09 archive/restore | API/service/tests có. IMPLEMENTED CORE PATH. |
| C-AC10–11 RBAC/feed/comment | Core logic/routes/tests có. IMPLEMENTED CORE PATH, không phải full system acceptance. |
| C-AC12 Service JWT boundary | Shared package and Core dependency tests reject invalid claims/User JWT; existing GET remains X-Service-Key pending CORE-T03 migration. | PARTIAL; runtime route/consumer migration pending. |
| C-AC13 actions/fail-closed | check_class_action và tests có; CORE-T03 generic adapter/action map chưa có. PARTIAL. |
| C-AC14–16 outbox/offline isolation | Core outbox/worker/retry có; cross-service failure tests chưa đủ. PARTIAL. |
| C-AC17 deletion jobs | Không có application job/event/completion flow. MISSING/BLOCKED. |
| C-AC18–19 frontend contract/DB boundaries | Core API contract, live adapter và boundary tests có; Notification extraction chưa làm. IMPLEMENTED/PARTIAL. |
| C-AC20 real integration | Document/Learning/AI/Notification contracts chưa cùng chạy. NOT VERIFIED. |

## 9. Revised backlog và đường tích hợp

| CORE task | Hiện trạng | Phạm vi còn lại; không viết lại |
|---|---|---|
| CORE-00 | Discovery task hiện tại | Chờ Technical Lead review |
| CORE-01 | Core schema/migrations head 0014 | Reuse; additive migration chỉ khi có gap đã duyệt |
| CORE-02 | User auth/session/rate limit | Reuse; SYS-02 Service JWT là phần riêng của system foundation |
| CORE-03 | Classroom/Admin/membership/teacher assignments | Reuse; resolve join-code/OWNER conflicts trước thay đổi |
| CORE-04 | Legacy GET access + X-Service-Key | Nâng adapter/route lên CORE-T03 POST và shared JWT; critical prerequisite |
| CORE-05 | Social/feed/comment | Reuse; không rewrite |
| CORE-06 | Core outbox + local Notification worker | Thêm per-target delivery/extraction contract cùng NTF; không chia sẻ Core DB |
| CORE-07 | Distributed account deletion chưa có | Bị chặn bởi retention, owner policy, durable completion contract |
| CORE-08 | Core frontend/API integration có | Chỉ đổi gateway ownership khi NTF/Document contracts ổn định |
| CORE-09 | Cross-service acceptance chưa có | Sau Core-T03/SYS-02 và các service vertical slices |

### Shortest vertical slice đề xuất

1. SYS-02 Service JWT dùng chung + CORE-T03 authorization/check với action đã map, current membership và fail-closed behavior.
2. Document: teacher upload một fixture trong allowlist đã chốt, tạo version/grant; Document lưu source và stream đúng version qua internal API.
3. AI: nhận durable ingestion job, index đúng version, báo readiness; query kiểm Core class action và Document grant trước retrieval/trả answer; citation có document_id/version_id.
4. Learning: từ cùng document_version_id tạo draft Practice/Question qua AI; Learning kiểm D6, validates schema/source, teacher review trước publish; student thử bài.
5. Notification event nối sau event/recipient contract freeze; không chặn slice đầu.

Đây là đề xuất, không phải phê duyệt endpoint/schema hoặc bắt đầu CORE-01. NTF có thể phát triển song song sau auth/event freeze theo Master Plan.

## 10. Kiểm thử và Execution Environment

### Local

| Command | Exit | Kết quả |
|---|---:|---|
| rtk git fetch origin | 0 | Fetch hoàn tất |
| rtk git pull --ff-only origin codex/rag-technical-discovery | 0 | Up-to-date tại 27f5f63 |
| rtk proxy .venv/Scripts/python.exe -m pytest tests/test_common.py tests/classroom/test_contract.py tests/notification/test_contract.py tests/security/test_boundaries.py -q -p no:cacheprovider (workdir services/core) | 0 | 70 passed in 1.57s; unit/contract/boundary slice, không dùng PostgreSQL |
| rtk proxy .venv/Scripts/python.exe -c 'import ast,pathlib; files=list(pathlib.Path("app").rglob("*.py")); [ast.parse(p.read_text(encoding="utf-8"),filename=str(p)) for p in files]; print(f"python_files={len(files)} syntax_errors=0")' | 0 | 88 file Python parse, 0 syntax errors |
| rtk proxy .venv/Scripts/ruff.exe check app/common/auth_dependencies.py app/common/security.py app/common/config.py app/modules/classroom/public.py app/modules/classroom/schemas.py app/modules/classroom/router.py app/modules/notification app/common/outbox.py app/background_worker.py (workdir services/core) | 0 | All checks passed |

### Server/testing blocker

Không chạy full suite, Docker build hoặc integration test trên server vì không có SSH endpoint đang xác minh được:

- SSH config hiện không có host entry.
- Port 1790: BatchMode + StrictHostKeyChecking kết thúc exit 1, connection reset từ 49.12.8.39:1790.
- Port 1407: exit 1 vì host key đổi; host mới báo SHA256:Jx/UwqXnoj7LMxM/F764ITvw7PzDG1rxIG6sferapsM, khác known_hosts. Strict checking đã từ chối; không cập nhật known_hosts hoặc bỏ qua kiểm tra.
- Không chạy lệnh trên server hoặc Production. Cần owner cung cấp/xác minh Testing host/port/fingerprint trước full test.

## 11. Blockers và trạng thái

- CORE-T03 generic authorization/action registry chưa được triển khai; cần chốt action-to-current-policy mapping.
- SYS-02 shared signer/verifier package and Core FastAPI dependency are implemented locally; no key material is provisioned, legacy GET/consumer migration and server verification remain pending.
- CORE-D04 join code/invite và owner-transfer terminology xung đột Business Rules; không implement trước khi thiết kế được sửa.
- Notification chưa tách khỏi Core DB/worker; cần NTF event inbox/recipient contract và migration riêng.
- CORE-T08 account deletion, retention, per-target completion và durable cleanup chưa triển khai.
- Cross-service Document/Learning/AI authorization and event delivery chưa verified.
- Full server/DB test bị chặn bởi SSH host access verification.

Không sửa application code/config/schema, không tạo migration, không bắt đầu CORE-01, không commit/push/merge/deploy.

**Kết thúc:** CORE-00 — DISCOVERY APPROVED, CLOSED — DOCUMENTATION PENDING COMMIT.
