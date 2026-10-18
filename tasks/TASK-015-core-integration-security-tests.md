# TASK-015: Core Comprehensive Security & Integration Test Suite

- **Mã Task:** `TASK-015`
- **Giai đoạn:** `G2 — Core tích hợp`
- **Owner chính:** `Cả nhóm (TV1, TV2, TV3, TV4)`
- **Module:** `services/core/tests/`
- **Business Rules:** `A1–A8`, `F1–F5`, `H1–H5`, `K2–K5`, `L1–L3`, `M1–M2`, `M5`, `O2`, `O4`
- **Quality Attributes:** `QAS-04`, `QAS-05`, `Core-01` đến `Core-06`
- **Tài liệu căn cứ:** [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#6-kiểm-thử-core-g1g2), [IMPLEMENTATION_ROADMAP.md](../docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md#checklist-nghiệm-thu-core)

**Cập nhật sau PR #10 (2026-10-19):** Backend Core trên `main` commit `2f7d70a` đã chạy lại **342 passed, 0 skipped** với PostgreSQL 16; Rule evidence có 342 cases và 0 skipped/failed scenario. [CI PR head `bb7f88d`](https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant/actions/runs/39157402992) đạt `core-tests`, `compose-smoke`, `web-build`. Đo tải follow-up 10 phút: 56.229 request, 100% HTTP 200, không sai scope, backend p95 18,79 ms, client p95 1,17 giây. Owner approval, Web E2E, user-facing SLO và full TP-01 chưa có bằng chứng nghiệm thu.


## Rà soát đồng bộ — 2026-10-16

**Hiện trạng tại ngày 2026-10-16:** repo có test Common/Identity/health/migration; bộ Classroom/Social/Notification/Administration chưa được tích hợp ở thời điểm đó. Đây là mốc lịch sử, không phải trạng thái hiện tại.

**Cần sửa:** thay concurrent join approval/ownership transfer và E2E xin mã vào lớp bằng Admin provisioning, roster AUTO/MANUAL, teaching assignment và transfer; tách lịch sử cá nhân khỏi quyền tham gia lớp hiện tại.

**Phụ thuộc:** mỗi owner bổ sung test cùng TASK-001–014; TASK-016 chạy suite trên PostgreSQL 16 và môi trường Compose sạch. Thiết kế chưa chốt phải có contract/fixture được duyệt trước nghiệm thu.

---

## 1. Mục tiêu

Kiểm chứng Core theo QAS-04/QAS-05 và Core-01–06 bằng PostgreSQL thực, test HTTP/public interface và E2E Web → Core → DB. Demo cá nhân bị gitignore chỉ hỗ trợ kiểm thử cục bộ; luồng UI chính thức còn phải được tích hợp trong apps/web.

**Scope hiện hành — người dùng chốt 2026-10-19:** task này thực hiện **backend Core**.
Không triển khai/chỉnh sửa frontend. Luồng xuyên module được kiểm chứng bằng HTTP →
Core workflows/worker → PostgreSQL và public interfaces thật. E2E Web ở mục tiêu
gốc được giữ là gate tích hợp riêng, ngoài phạm vi lần này; không dùng backend test
để đánh dấu Web đã nghiệm thu.

## 2. Kịch bản bắt buộc

### 2.1. Quyền và dữ liệu — Core-01/QAS-04

- Cross-school/class/user/resource, scope null, ID giả và quyền đổi sau khi phát hành JWT; LOCKED/PENDING không vượt qua auth.
- Chỉ Admin tạo lớp, roster, phân công, ghi danh, chuyển lớp và archive/restore; Student không self-register/join/leave; Lecturer không dùng global role để tự cấp quyền.
- Membership kết thúc chặn nội dung mới/participation/AI mới; owner đọc bài đã nộp/điểm/chat/notes/appeal theo action giới hạn. Document source vẫn cần grant hiện hành, Admin không mặc định đọc private chat.
- ARCHIVED chặn hoạt động chung; ngoại lệ notes/bookmarks cá nhân theo O2 được kiểm thử ở Document khi có service, không coi mock là E2E đã chạy.

### 2.2. Cạnh tranh và toàn vẹn — Core-02

- 100 thao tác sync/transfer/import cạnh tranh có kiểm soát: một membership hiện hành/cặp, giữ lịch sử, không ghi đè MANUAL.
- MANUAL→AUTO preview/confirm, preview stale, duplicate confirm, retry sau mất phản hồi/restart; kiểm chứng bảo đảm idempotency theo thiết kế đã duyệt.
- Thay giáo viên chính cạnh tranh giữ H2; assignment cũ hết hiệu lực, consumer không tiếp tục cấp quyền cũ.
- Import CSV/Excel lỗi/trùng/re-import và rollback theo batch contract; không cache/phát lại activation code như response thường.

### 2.3. Xác thực — Core-03

- Student không email: provision/reissue/activate/login/refresh/Admin recovery; expiry/purpose/replay/username duplicate, không tự mở LOCKED; staff email auth vẫn hoạt động.
- Legacy migration giữ ID/hash/dữ liệu, chỉ chuyển bằng Admin cùng trường; email token cũ không bypass Student activation.
- Refresh rotation/family replay, logout-all/password/status/role revocation, cookie attributes/clear, CSRF Origin/Referer, limiter và stale idempotency response.
- Register request hợp lệ luôn 403; activation/login/reset đúng giới hạn, không dùng test register 201 như luồng phát hành.

### 2.4. Tích hợp — Core-04

- Admin provision → Student activate → Admin roster/AUTO hoặc MANUAL → thông báo → Student feed/comment/calendar → moderation có audit → transfer/archive.
- Kiểm tra relation class–post–comment, soft delete list/detail, recipient-only notification, worker retry/crash/dedup và producer rollback.
- Admin role/lock/data request ACCESS/EXPORT/CORRECTION/DELETE có xác minh, audit/redaction, không tự xóa liên service.
- Calendar LEARNING read-only; duplicate/out-of-order deadline và notification đúng contract. Learning chưa triển khai thì chỉ ghi kết quả contract/projection test.
- Bộ test hợp đồng bảo vệ module boundaries; không có import repository/model chéo hoặc SQL xuyên service.

### 2.5. Hạ tầng và hiệu năng — Core-05/06

- TASK-014/016: upgrade/drift/legacy data preservation, clean Compose startup, installed wheel/non-root, readiness DB/schema, outage/recovery, lint/format/OpenAPI và coverage gates.
- Đo p95 danh sách lớp ≤500 ms và thành công ≥99% theo TP-01 sau khi có API danh sách lớp được duyệt; không tự coi GET /classes là route đã triển khai.
- Ghi máy/cấu hình/tải/script và kết quả thật. Không suy ra KPI tải/RAG hoặc toàn bộ G2 chỉ vì unit tests/CI green.

## 3. Tiêu chí nghiệm thu

- [x] Tất cả module Core hiện có có test chạy thật trên PostgreSQL 16: 342 passed, không skip.
- [x] Core-01–06 có catalog Rule ID → scenario → kết quả, JUnit/coverage/local artifacts và CI xuất evidence; service chưa có được ghi pending. Core-06 chỉ đạt ngưỡng trong phạm vi backend class-list của bài đo local, không coi là full TP-01.
- [ ] Web E2E đầy đủ: **ngoài scope backend người dùng chốt 2026-10-19**, không thay đổi apps/web hoặc dùng backend test để nghiệm thu Web.
- [x] Các ca truy cập trái phép trong phạm vi test bị chặn sau fix; không quan sát rò rỉ trong suite hữu hạn. Pending services, client latency, cache durability và remote review/CI được ghi rõ; không khẳng định bảo đảm tuyệt đối.
- [x] Remote CI trên PR #10: `core-tests`, `compose-smoke`, `web-build` đạt ở head `bb7f88d` trước squash merge.
- [ ] Reviewer/owner approval và nghiệm thu toàn Core G2 hoặc mixed-service TP-01.

## 4. Triển khai backend — 2026-10-19

- Thêm `tests/security/`: fixture database con PostgreSQL 16, real HTTP authentication/authorization, workflow provisioning → activation → enrollment → feed/comment/calendar → worker notification → moderation/audit → transfer/archive/revoke. Mỗi request vẫn dùng Identity/class access thực, không mock quyền thành allow.
- Permission matrix kiểm tra role/status/school hiện hành với JWT đã phát hành, scope null/khác trường/lớp, parent-child resource, ID giả, Identity lookup lỗi fail closed, Admin-only và route tự join/leave/register bị chặn. History action của Core có test riêng; chưa coi đó là dữ liệu Learning/AI/Document E2E.
- Core-02: 100 sync/roster operations, 100 transfer retries và 100 import confirmations cạnh tranh (16 workers mỗi scenario), đối soát membership ACTIVE/history, MANUAL không bị ghi đè. Import restart bằng app/cache mới giữ result IDs và không phát lại code; non-import cache vẫn process-local theo contract.
- AST architecture guard kiểm tra import public giữa các domain và literal SQL sang service khác, có test detector. Không coi static scan là chứng minh tuyệt đối cho dynamic code.
- `scenarios.json` + `evidence.py` nối Rule ID → scenario → JUnit/result; missing/skip/failure không được tính đạt. Có mục pending cho service chưa triển khai và Web ngoài scope. CI lưu rule evidence, JUnit/coverage; thêm job đo tải backend 10 phút qua workflow_dispatch.
- Script `tests/performance/class_list_load.py` tạo database/load fixtures riêng, đo 100 user/10 lớp/50 Student mỗi lớp, 30 giây warmup + 600 giây, cùng HTTP pool và stagger lịch đóng. Báo cáo backend ASGI p95 lẫn client p95, tỷ lệ thành công, scope check và cấu hình máy/DB. Đây là Core subset TP-01, không nghiệm thu toàn mixed-service/RAG.
- Sửa hai vấn đề phát hiện khi kiểm thử: cached Classroom mutation phải recheck tài nguyên nguồn/đích/created resource theo scope hiện hành; thêm admission queue trước sync dependencies để hạn chế DB pool starvation, giữ permit qua cleanup, timeout trả no-store 503/Retry-After, health bypass. Mặc định pool 5+10; profile đo dùng 15+0 để giữ kết nối, cùng trần tối đa 15.
- Shared/owner review: TV1 Identity/public/Common, TV2 Classroom/replay, TV3/TV4 test matrix và CI. Không đổi schema/Business Rules, không thêm HTTP nghiệp vụ, không push/commit/deploy; `apps/web` không có thay đổi.
- Hướng dẫn, giới hạn và lệnh: [backend test guide](../services/core/tests/README.md). Bằng chứng local bên dưới là mốc thực hiện; CI PR #10 được ghi trong cập nhật đầu tài liệu.

## 5. Bằng chứng local — 2026-10-19

- PostgreSQL **16.14**, Python **3.12.14**: full suite với `-W error --cov=app --cov-branch --junitxml=test-results.xml` đạt **342 passed / 0 failed / 0 skipped**, 651.17 giây; gồm **29 ca mới** của TASK-015. Coverage tổng **90.80% (làm tròn 91%)**, line **93.51%**, branch **78.28%**. Gate Identity public riêng **17 passed, 100% line/branch**; không coi coverage tổng là 100%.
- `ruff check` và `ruff format --check` đạt **139 file**; `git diff --check` đạt. CI YAML được parse/kiểm tra cấu trúc. Tại lúc ghi evidence local chưa có remote run; CI PR #10 sau đó đạt như cập nhật đầu tài liệu.
- Core-02 gồm **100 thao tác/scenario** × sync/transfer/import, 16 workers; đối soát membership/history, toàn bộ danh sách MANUAL, durable confirm sau restart. Hai ca delivery có fixture event đã due rõ ràng, không thay production worker/clock hoặc test retry/backoff. Lượt full đầu chạy cùng load có 2 failure ở assertions delivery; rerun riêng hai ca đạt, sau precondition fixture lượt full độc lập đạt toàn bộ.
- Backend Compose từ volume sạch: migrate hoàn tất trước Core/worker, UID **10001**, app wheel trong site-packages, OpenAPI/admission, Alembic check, live/ready; dừng DB → ready **503**, live vẫn **200**, restart DB → ready phục hồi. Chỉ chạy db/migrate/core/notification-worker, không build/start Web; project/volume test đã dọn.
- Core-06: 100 user, 10 lớp × 50 Student, warmup 30 giây + cấu hình 600 giây, completion 604.91 giây; **11.416 request**, **11.415 HTTP 200**, **1 transport/contract error**. Backend ASGI p95 **96.51 ms**, success **99.9912%**, scope mismatch **0**. Máy Windows 12 logical CPU/RAM ~16.9 GB, PostgreSQL Docker loopback, pool **15+0**.
- **Giới hạn hiệu năng:** client p95 **15.58 giây**, max **45.72 giây** trong lượt đo dùng chung máy với coverage/build. Backend samples 11.415 tương ứng các request đến ASGI; lỗi phía client vẫn tính vào mẫu success. Đây là closed-loop traffic, không phải cam kết 100 request/giây, không chứng minh độ trễ người dùng tốt hoặc full TP-01. Không có Document/Learning/AI/intelligence traffic; cần benchmark môi trường riêng trước nghiệm thu toàn hệ thống.
- **Follow-up tải 2026-10-19:** Không chạy suite/build đồng thời; vẫn dùng máy Windows dùng chung, không cô lập tài nguyên. PostgreSQL 16.15, migration 0012, pool 15+0; 100 users / 10 classes / 500 Students trong 601 giây: **56.229 request, 56.229 HTTP 200, 0 scope mismatch**, backend p95 **18,79 ms**, client p95 **1,17 giây**, max client **9,99 giây**. Ngưỡng backend subset đạt; kết quả thấp hơn lượt chạy cùng coverage/build trước đó nhưng chưa xác định nguyên nhân và chưa xác nhận user-facing SLO.
- Safe aggregate artifacts: [verification](../services/core/test-evidence/task015/verification.json), [Rule results](../services/core/test-evidence/task015/rule-results.json), [load ban đầu](../services/core/test-evidence/task015/core-load-2026-10-19.json), [load follow-up](../services/core/test-evidence/task015/core-load-followup-2026-10-19.json), [runtime](../services/core/test-evidence/task015/runtime.json). JUnit/coverage raw nằm ở output test bị gitignore hoặc CI artifact; không đưa credential/header/code vào báo cáo tổng hợp.
