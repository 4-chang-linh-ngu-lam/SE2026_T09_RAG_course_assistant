# CORE-00-R1 — Revised Backlog và Engineering Review Response

**Trạng thái:** CORE-00 — DISCOVERY APPROVED, CLOSED; SYS-02 implementation và design updates đang chờ Technical Lead Engineering Review, chưa commit.
**Baseline:** 27f5f6371d246f027ae4f501c083e125b7cb1961
**Ràng buộc:** discovery-only; không sửa code/schema/migration; không bắt đầu CORE-01; không commit/push.

## 1. Revised CORE-01–09 disposition

| Task | Disposition | Current evidence | Remaining scope/dependency |
|---|---|---|---|
| CORE-01 DB/migration | VERIFY | Core schema/migrations đã có đến 0014; Model Registry và migration safety hiện hành. | Chỉ tạo additive migration nếu CORE-T01 gap được duyệt; không lập lại schema. |
| CORE-02 Auth/session | REUSE | User login/JWT/refresh/session revoke, live status/version checks và rate limits đã có trong Identity. | Không viết lại user auth. Shared Service JWT thuộc SYS-02/CORE-T04. |
| CORE-03 Classroom/membership | VERIFY | Admin catalog/class/roster, AUTO/MANUAL, teaching assignment, archive/restore và current action checks hiện có. | Resolve conflict CORE-D03/D04/C-AC01/05/06/07 trước mở rộng; giữ Business Rules. |
| CORE-04 Internal authorization/service auth | IMPLEMENT | check_class_action + legacy GET/X-Service-Key còn; SYS-02 signer/verifier/dependency đã có; CORE-T03 POST/action registry chưa có. | Add CORE-T03 adapter after action mapping approval; preserve legacy route during migration. |
| CORE-05 Feed/comment/moderation | REUSE | Core Social/Calendar routes, services, audit/outbox và tests hiện có. | Reuse; không rewrite. |
| CORE-06 Outbox/delivery worker | EXTEND | Core outbox/notification worker atomic, retryable và dedup nhưng cùng Core DB/process. | Per-target delivery/REST contract với Notification Service; tách credential email delivery khỏi NTF. |
| CORE-07 Account deletion | DEFER | Chưa có DELETION_PENDING/account_deletion_jobs/user.deletion_requested implementation; DELETE data-request chỉ là manual PENDING. | Chờ retention, owner policy, per-target completion và cleanup contracts. |
| CORE-08 API/frontend compatibility | VERIFY | Core public API và live frontend adapters hiện có; future Gateway route owners khác khi service tách. | Kiểm route/auth/error contracts cùng SYS-03/SYS-04; không đổi frontend ở CORE-00. |
| CORE-09 Integration/security/fault/load | DEFER | Unit/contract tests và local Compose patterns tồn tại; Document/Learning/AI/NTF chưa đủ để real E2E. | Chạy sau shared JWT/Core-T03 và service vertical slices; full Testing server hiện bị chặn. |

### Dependency/parallelism theo Master Implementation Plan

- **Phase 1 foundation:** SYS-01 DB isolation, SYS-02 shared Service JWT, SYS-03 gateway; CORE-01–04 phụ thuộc discovery/contract freeze.
- CORE-01–03 hiện có code mạnh; chỉ xác minh gap, không phải lệnh rewrite. CORE-04 là phần Core-specific cần extend sau SYS-02.
- **Phase 2:** Document, Learning và Notification có thể triển khai song song khi auth/event contracts ổn định; Core CORE-05/06 có thể tiếp tục độc lập, nhưng NTF delivery adapter phụ thuộc event contract.
- **Phase 3–5:** service AI jobs/D6/indexing, frontend, security/E2E/load/backup acceptance. CORE-07 vẫn bị retention/completion policy chặn.
- Không có task nào trong bảng được bắt đầu bởi CORE-00.

## 2. Coverage matrix — 20 Core Acceptance Criteria

| AC | Current evidence | Status |
|---|---|---|
| C-AC01 Register hợp lệ/email trùng | API contract trả 403 cho public register; Business Rules chặn self-registration Student. | CONFLICT — sửa acceptance; kiểm tra register bị chặn/provisioning thay thế. |
| C-AC02 Login đúng/sai, rate limit, không lộ hash | Identity router/service, token hashing/rate-limit logic và tests hiện có. | IMPLEMENTED PATH; full CI không chạy trong CORE-00. |
| C-AC03 Refresh rotation/reuse/logout revoke | Identity refresh session/hash/revoke implementation và migration hiện có. | IMPLEMENTED PATH; real PostgreSQL suite không chạy trong lượt này. |
| C-AC04 Suspend/delete pending chặn JWT cũ | get_current_user kiểm ACTIVE/session_version; distributed DELETION_PENDING không có trong code. | PARTIAL. |
| C-AC05 Class đúng một owner | Admin create class + assignments atomic; source model/API dùng PRIMARY lecturer, không chứng minh CORE-D03 OWNER model. | PARTIAL/DOMAIN MAPPING OPEN. |
| C-AC06 Invite/join dedup | Business Rules A6/API Contract cấm join-code/join-request; CORE-D04/C-AC06 mâu thuẫn. | CONFLICT. |
| C-AC07 Owner transfer atomic | Core API không có owner-transfer; Business Rule H1 giới hạn teaching assignment cho Admin. | CONFLICT / NOT IMPLEMENTED. |
| C-AC08 Remove member revoke Document/Learning/AI | Core current membership checks/roster removal hiện có; external services chưa tích hợp. | PARTIAL; downstream E2E chưa verified. |
| C-AC09 Archive read-only/restore | Admin archive/restore và current class access checks hiện có. | IMPLEMENTED CORE PATH. |
| C-AC10 Outsider/student không leo quyền | Role/current-school checks và security/class tests hiện có. | IMPLEMENTED PATH; chỉ subset tests chạy. |
| C-AC11 Feed/comment rights/moderation audit | Core Social services/routes/audit/tests hiện có. | IMPLEMENTED CORE PATH. |
| C-AC12 Internal API từ chối user JWT/sai Service JWT claims | Shared SYS-02 verifier/Core dependency từ chối User JWT và claim không tin cậy trong targeted local tests; legacy GET vẫn dùng X-Service-Key. Chưa có POST CORE-T03 route. | PARTIAL — package/dependency đã kiểm chứng local; route/consumer migration và server verification pending. |
| C-AC13 Action registry/fail-closed | check_class_action và tests có; CORE-T03 generic endpoint/action registry chưa có. | PARTIAL. |
| C-AC14 Outbox atomic, recovery, dedup | Transactional outbox, worker retry/dedup và PostgreSQL tests hiện có. | IMPLEMENTED CORE PATH; chưa full server run. |
| C-AC15 Notification offline không chặn post | Outbox cho phép mutation commit tách khỏi delivery; Notification worker retryable. | IMPLEMENTED CORE-local; không phải NTF service acceptance. |
| C-AC16 AI/Document/Learning offline không chặn Core độc lập | Producer writes dùng outbox; cross-service services/runtime chưa có. | PARTIAL; fault integration chưa verified. |
| C-AC17 Distributed deletion jobs/retry | Không thấy application model/migration/worker cho distributed deletion. | MISSING / BLOCKED bởi retention/owner/completion contract. |
| C-AC18 Frontend contract/error compatibility | Core API contract, web live adapters và contract tests có. | IMPLEMENTED CORE path; mixed-service Gateway E2E chưa verified. |
| C-AC19 Không cross-service SQL/FK/leak | Core schema ownership và boundary guard tests hiện có; Notification FK user nằm nội bộ Core hiện tại. | IMPLEMENTED CORE boundary; phải đổi boundary khi Notification tách DB. |
| C-AC20 Real integration authorization/event delivery | Document/Learning/AI/Notification chưa cùng chạy dưới contracts mới. | NOT VERIFIED. |

**Business rule precedence:** C-AC01/06/07 và CORE-D03/D04 không được code như written khi conflict với BUSINESS_RULES.md. Yêu cầu sửa design/AC là quyết định của Technical Lead.

## 3. Shortest vertical slice đề xuất

1. SYS-02 Service JWT shared foundation + CORE-T03 POST authorization/check, với action registry đã reconcile và fail-closed behavior.
2. Document upload một fixture allowlist đã duyệt, tạo source/version/grant; Document stream exact version và checksum cho AI.
3. AI nhận durable ingestion job, index đúng version, báo readiness. Tutor query yêu cầu Core action + Document current grant trước retrieval và revalidation trước response; citation mang document_id/version_id.
4. Learning gọi AI tạo draft Practice/Question từ cùng document_version_id; Learning kiểm D6 và schema/source; giáo viên duyệt trước publish, học sinh mới làm attempt.
5. Notification event nối sau khi event/recipient contract freeze; không đặt trên critical path đầu.

Đây là đề xuất sequencing, không phải phê duyệt endpoint/schema hoặc bắt đầu CORE-01.

## 4. CORE-RV01–06 response

| Review ID | Finding | Resolution | Evidence | Remaining Blocker | Status |
|---|---|---|---|---|---|
| CORE-RV01 | Truy vết Business Rules/FRS gốc và mọi design conflicts. | Ma trận tại 01 đối chiếu A1–A8, H1–H2, FRS-C06–C10, CORE-D/T, SYS/DOC/LRN/NTF. Không sửa accepted design. | BUSINESS_RULES.md:12–19,70–72; FRS Core:73–120; Core API Contract:46–74,174–184. | Technical Lead phải quyết định sửa CORE-D03/D04/C-AC01/05/06/07. | RESOLUTION PROPOSED |
| CORE-RV02 | Mapping check_class_action/legacy GET sang CORE-T03. | Ma trận action tại 02; giữ decision logic trong Core, dùng REST adapter, giữ GET legacy tương thích. | classroom/public.py:113–174; schemas.py:19–26; router.py:482–493. | POST endpoint/resource mapping và DOCUMENT_SHARE/MANAGE semantics chưa có. | PARTIAL / ACTION MAP OPEN |
| CORE-RV03 | SYS-02 shared Service JWT foundation/migration. | Shared `lumi-service-auth` package and Core dependency implemented locally; no auth riêng in Document. | packages/service-auth, Core adapter/dependency, SYS02 report. | Key provisioning/rotation, consumer adoption and CORE-T03 route migration unverified. | IMPLEMENTED LOCALLY; OPS/CONSUMERS PENDING |
| CORE-RV04 | Xác định phần Core đã hoàn thành, tránh rewrite. | CORE-01/02/03/05 được đánh REUSE/VERIFY; CORE-04 EXTEND; CORE-06 EXTEND; CORE-07 DEFER; CORE-08 VERIFY; CORE-09 DEFER. | API_CONTRACT.md:3,46–74,80–122; README.md:13,33–41,59; migrations head 0014. | Một số AC/flows chưa integration-tested; conflicts cần resolve trước thay đổi. | RESOLVED IN DISCOVERY |
| CORE-RV05 | Notification module/worker đang nằm trong Core và khả năng reuse. | Chỉ reuse pure event semantics/tests; không chuyển ORM/worker vì FK Core, shared DB, imports nội bộ. Extraction plan cần NTF DB/inbox/API + Core per-target outbox. | notification/models.py:11–13; worker.py:21–76; events.py:11–19,79–140; background_worker.py:14–23. | NTF-T03/T04 recipient, event, JWT và deletion completion contracts. | RESOLVED IN DISCOVERY |
| CORE-RV06 | Revised backlog, first vertical slice và kiểm thử/server. | Backlog/disposition, 20 C-AC matrix và phased Document→AI→Learning slice tại 03. Local tests/static checks ghi rõ; không chạy full server tests. | SYS MIP; results §5 of this report; SSH attempts below. | SERVER-01 SSH Testing access/host key; full PostgreSQL/Compose/integration evidence còn thiếu. | PROPOSED; SERVER-01 BLOCKER |

## 5. Command, test và server evidence

Local test command (workdir services/core):
rtk proxy .venv/Scripts/python.exe -m pytest tests/test_common.py tests/classroom/test_contract.py tests/notification/test_contract.py tests/security/test_boundaries.py -q -p no:cacheprovider
**Exit 0:** 70 passed in 1.57s. Đây là test slice không kết nối PostgreSQL; không đại diện full Core suite.

Static parse command (workdir services/core):
rtk proxy .venv/Scripts/python.exe -c 'import ast,pathlib; files=list(pathlib.Path("app").rglob("*.py")); [ast.parse(p.read_text(encoding="utf-8"),filename=str(p)) for p in files]; print(f"python_files={len(files)} syntax_errors=0")'
**Exit 0:** 88 file Python parsed, 0 syntax errors.

Ruff command (workdir services/core):
rtk proxy .venv/Scripts/ruff.exe check app/common/auth_dependencies.py app/common/security.py app/common/config.py app/modules/classroom/public.py app/modules/classroom/schemas.py app/modules/classroom/router.py app/modules/notification app/common/outbox.py app/background_worker.py
**Exit 0:** All checks passed.

### Server/testing blocker

Không chạy full suite, Docker build hoặc integration test trên server vì không có SSH endpoint đang xác minh được:

- SSH config hiện không có host entry.
- Port 1790: BatchMode + StrictHostKeyChecking kết thúc exit 1, connection reset từ 49.12.8.39:1790.
- Port 1407: exit 1, host key changed; host mới báo SHA256:Jx/UwqXnoj7LMxM/F764ITvw7PzDG1rxIG6sferapsM, khác known_hosts. Strict checking đã từ chối; không sửa known_hosts hoặc bỏ qua verification.
- Không chạy test server/Production hoặc truy cập database ngoài local test.

**SERVER-01:** cần Testing endpoint/port và fingerprint được xác nhận qua CKEY console trước full tests, Docker build hoặc integration test.

## 6. Open blockers và stop condition

- CORE-T03 generic authorization/action registry chưa triển khai; cần chốt action-to-current-policy mapping.
- SYS-02 shared package is implemented locally; key provisioning/rotation, CORE-T03 route migration and consumer adoption remain pending.
- CORE-D04 join code/invite và owner-transfer terminology xung đột Business Rules; không implement trước khi design được sửa.
- Notification chưa tách khỏi Core DB/worker; cần NTF event inbox/recipient contract và migration riêng.
- CORE-T08 account deletion, retention, per-target completion và durable cleanup chưa triển khai.
- Cross-service Document/Learning/AI authorization/event delivery chưa verified.
- Full server/DB test bị chặn bởi SSH host access verification.

Không sửa application code/config/schema, không tạo migration, không bắt đầu CORE-01, không commit/push/merge/deploy.

**Kết thúc:** CORE-00 — DISCOVERY APPROVED, CLOSED — DISCOVERY BASELINE; SYS-02 implementation pending Engineering Review, chưa commit.
