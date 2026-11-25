# CORE-00-R1 — Authorization và Service JWT foundation

**Trạng thái:** CORE-00/R1 approved; shared `lumi-service-auth` package and Core signer/verifier adapter/dependency implemented locally; key provisioning/rotation, consumer migration and server verification pending.
**Scope:** discovery snapshot, được cập nhật sau SYS-02 implementation; không triển khai CORE-04 hay CORE-T03 adapter.

## 1. Hai luồng authentication khác nhau

### User access token

- Identity phát User access JWT bằng SECRET_KEY, thuật toán cấu hình hiện tại HS256; claim gồm sub, roles, session_version, iat, exp. Tham chiếu services/core/app/common/security.py:27–70 và app/common/config.py:18–21.
- get_current_user decode JWT rồi tra Identity hiện hành; user phải ACTIVE và session_version còn khớp. require_roles dựa vào role DB hiện hành, không coi role claim cũ là authority: app/common/auth_dependencies.py:48–83.
- User refresh token là credential riêng, lưu hash/rotation trong Identity. Không dùng User JWT để gọi internal services.

### Service credential hiện tại

- verify_internal_service_key nhận X-Service-Key, so constant-time với INTERNAL_SERVICE_SECRET. Secret thiếu trả 503, sai key trả 401; đúng key luôn được cấp scope core:check_access: auth_dependencies.py:86–96.
- Config internal_service_secret là SecretStr tối thiểu 32 ký tự: common/config.py:26.
- Đây là static shared-key check, không có claim issuer/audience/expiry/source identity, không có scope-specific token, không thể xác định caller nào nếu nhiều service dùng chung key.

### Service JWT target

SYS-D05/SYS-02 và CORE-T04 chốt User JWT + Service JWT dùng chung toàn hệ thống, với issuer/audience/scope/expiry/source identity; signer và verifier contract hiện nằm trong package chung, còn key provisioning/distribution/rotation operations pending. Core User JWT hiện tại và Service JWT không thể dùng thay thế cho nhau. Document/Learning/AI/Notification phải dùng chung foundation, không tự tạo issuer/key mechanism từng service.

## 2. Authorization decision hiện tại

Internal router ở services/core/app/modules/classroom/router.py:60–63 dùng prefix /internal/v1. GET /classes/{class_id}/access tại router.py:482–493 nhận class_id trên path, user_id/action qua query, yêu cầu scope core:check_access, gọi public.check_class_action và trả InternalAccessResponse. Đây là route class-scoped cũ, không phải CORE-T03.

check_class_action tại classroom/public.py:113–174:
1. từ chối action ngoài ClassAccessAction;
2. yêu cầu user tồn tại, ACTIVE, có school_id;
3. yêu cầu class tồn tại và cùng trường;
4. đọc role/membership/teacher assignment hiện hành;
5. áp policy hiện tại theo action; optional FOR SHARE lock cho caller transaction.

Class action behavior quan trọng:
- READ_DOCUMENT_SOURCE: current Student membership hoặc current Lecturer assignment; không kiểm Document grant/version.
- USE_AI_TUTOR: chỉ Student hiện hành trong class ACTIVE.
- PARTICIPATE_CURRENT_CLASS: class ACTIVE và Student/Teacher hiện hành.
- GRADE_SUBMITTED_WORK: class ACTIVE và Teacher hiện hành; code comment giao Learning check assignment cụ thể.
- READ_OWN_HISTORY có thể cho phép Student đã hết membership; không cấp source access.
- MODERATE_CLASS_CONTENT hiện cho Teacher hoặc ADMIN; không đồng nghĩa document owner/share permission.

## 3. Mapping toàn bộ action CORE-T03

Bảng này map đủ các action tại core-design/04_INTERNAL_API.md:5. Mapping là đánh giá tương thích, không sửa action registry accepted. Logic class-level của Core không thay thế resource authorization tại Document/Learning.

| Target Action | Existing Action | Existing Permission Logic | Compatible/Partial/Missing | Required Change | Evidence |
|---|---|---|---|---|---|
| DOCUMENT_READ | READ_DOCUMENT_SOURCE | User ACTIVE/same school và current Student membership hoặc Lecturer assignment; không xét Document grant/version. | PARTIAL | Thêm CORE-T03 action adapter; Document kiểm owner/grant/active version trước tải/truy vấn. | classroom/public.py:113–174; schemas.py:19–26 |
| DOCUMENT_SHARE | Không có action trực tiếp; MANAGE_CLASS_CALENDAR chỉ là Teacher+ACTIVE class. | Có predicate current teacher/class status, nhưng purpose khác share. | MISSING | Chốt quyền PRIMARY/ASSISTING theo Business Rules; không dùng calendar/moderation để overgrant. | classroom/public.py:151–158; BUSINESS_RULES.md:14,70 |
| DOCUMENT_MANAGE | Không có action trực tiếp. | Core không biết source owner/grant; các dữ liệu đó thuộc Document. | MISSING | Document kiểm source owner và local resource policy; Core chỉ cung cấp class/user gate khi cần. | CORE-T03 contract; DOC-D06 |
| AI_QUERY | USE_AI_TUTOR | Class ACTIVE và current Student. | PARTIAL | Xác nhận role scope của CORE-T03; Document/AI còn kiểm active grant và scope. Không tự mở cho Teacher. | classroom/public.py:161–163 |
| PRACTICE_ACCESS | PARTICIPATE_CURRENT_CLASS | Class ACTIVE và current Student/Teacher. | PARTIAL | Learning kiểm practice session, attempt, policy và resource ownership. | classroom/public.py:143–146; LRN-D03/D04 |
| ASSIGNMENT_CREATE | Không có action trực tiếp; MANAGE_CLASS_CALENDAR là predicate Teacher+ACTIVE, không tương đương assignment. | Có teacher eligibility một phần. | PARTIAL | Đăng ký action CORE-T03 sau khi rule chốt; Learning kiểm lớp, assignment và actor. | classroom/public.py:151–158; LRN-D01/D04 |
| ASSIGNMENT_SUBMIT | PARTICIPATE_CURRENT_CLASS | Class ACTIVE/current member; không kiểm due date, assignment, attempt hay recipient snapshot. | PARTIAL | Learning kiểm enrollment snapshot, attempt, deadline và submit idempotency. | classroom/public.py:143–146; LRN-T02/T05 |
| ASSESSMENT_MANAGE | Không có action trực tiếp; MODERATE_CLASS_CONTENT là moderation. | Teacher/Admin có predicate cho moderation/calendar, không có assessment-specific policy. | MISSING | Chốt policy/actor trong Learning; thêm Core action implementation theo CORE-T03, không map từ moderation. | classroom/public.py:147–158; LRN-D04/D06 |
| GRADE_MANAGE | GRADE_SUBMITTED_WORK | Class ACTIVE/current Teacher; code ghi rõ Learning phải xác minh submission assignment riêng. | PARTIAL | Reuse class gate; Learning kiểm grader assignment, grade lifecycle, audit và publish status. | classroom/public.py:164–174; LRN-D06 |
| ANALYTICS_VIEW | Không có action trực tiếp; READ_OWN_HISTORY không tương đương. | READ_OWN_HISTORY chỉ cho chính Student và membership history; không cấp teacher aggregate access. | MISSING | Chốt learner-data scope/O6; Learning sở hữu analytics resource check. | classroom/public.py:155–156; LRN-D09 |

Other existing actions READ_CLASS_CONTENT, MODERATE_CLASS_CONTENT, MANAGE_CLASS_CALENDAR và READ_OWN_HISTORY không được tự gán sang một CORE-T03 action khác nếu ý nghĩa không trùng. CORE-T03 endpoint vẫn chưa tồn tại trong code; hiện là GET class access legacy.

## 4. REST adapter tối thiểu, không overgrant

1. Bổ sung CORE-T03 POST /internal/v1/authorization/check theo accepted DTO: user_id, resource_type, resource_id, action → allowed. Endpoint dùng Service JWT của SYS-02/CORE-T04; không public qua gateway.
2. Đặt hiện thực Core policy phía sau một adapter/facade trong Core để reuse current identity, membership, teaching assignment và class-state decision. Không để Document gọi check_class_action trực tiếp hoặc truy vấn core.*.
3. Consumer gửi class resource/action để Core quyết định class-side gate; Document sau đó kiểm tra document_id, owner/grant, version status và local resource policy.
4. Giữ GET /internal/v1/classes/{class_id}/access + X-Service-Key làm compatibility route trong giai đoạn chuyển caller. Hai route phải gọi cùng policy implementation; không mở rộng legacy scope. Chỉ loại bỏ legacy key sau khi inventory/metrics xác nhận không còn caller và migration được duyệt.
5. CORE-T03 POST mới chỉ chấp nhận Service JWT đúng issuer/audience/scope/source; không fallback sang user bearer hoặc static key. Core/consumer outage trả fail closed, theo error contract.
6. Generic endpoint target chỉ trả allowed; nếu caller cần class_status để map 404/409, chốt DTO bổ sung trong CORE-T03 thay vì phụ thuộc response legacy.

Compatibility note: điểm reuse là quyết định nghiệp vụ bên trong Core, không phải wire compatibility. Legacy GET có response fields/query contract khác CORE-T03 POST nên adapter mới cần contract tests.

## 5. Service JWT migration plan

| Step | Phạm vi đề xuất | Gate |
|---|---|---|
| 0. Freeze trust contract | Implemented RS256 allowlist, issuer, service subject, audience, scopes, token_type, iat/exp/kid, max TTL 300s, skew <=30s | SYS-02/CORE-T04; secret-manager provisioning, issuer topology and rotation operations remain pending |
| 1. Shared foundation | Contract, signer/verifier và trust policy nằm trong package độc lập `packages/service-auth`; Core common chỉ map Settings và cung cấp FastAPI dependency. Service identity tách khỏi User identity. | Package cài độc lập đã được kiểm tra; key provisioning/rotation runbook, trust configuration và rollout consumer cần được duyệt |
| 2. CORE-T03 | Thêm POST authorization/check dùng Service JWT; giữ current GET/X-Service-Key route làm compatibility adapter | Contract tests cho authorized, denied, wrong scope/audience/issuer, expired |
| 3. Consumer migration | Document/Learning/AI/Notification client gọi POST bằng service audience/scope tối thiểu | Integration logs cho biết caller identity; fail closed |
| 4. Deprecation | Chặn legacy route/key sau khi mọi consumer đã chuyển và có rollout/rollback evidence | Không hardcode ngày; owner xác nhận không còn traffic |

User JWT HS256 vẫn phục vụ browser/Core session. SYS-02 implementation adopts RS256 allowlist, service subject/issuer/audience/scope/token_type, iat/exp/kid, max TTL 300 seconds and skew up to 30 seconds. Không chuyển User JWT key sang Service JWT. Secret-manager provisioning, issuer trust topology, key rotation runbook, consumer adoption và legacy retirement vẫn cần review/vận hành.

## 6. SYS-02 status update

CORE-00 là snapshot trước implementation SYS-02. Hiện shared package có signer/verifier; Core adapter/dependency và consumer cài độc lập đã qua targeted local tests. Không có POST CORE-T03 route và legacy GET vẫn dùng X-Service-Key. Chưa cấu hình key vận hành, chưa có rotation runbook hay consumer migration; kiểm thử full trên Testing server bị chặn bởi SERVER-01.

## 7. Test/contract matrix cần có trước exposure

- Legacy GET giữ đúng status/response/auth, không bị vô tình mở public.
- CORE-T03 POST: valid service JWT; reject user JWT; wrong service source, issuer, audience, scope, expired token, missing/invalid signature.
- Core current status/membership/assignment thay đổi ngay làm authorization result thay đổi; cross-school/unknown resource không leak.
- DOCUMENT_READ không cho qua nếu Document grant revoked/version inactive; Core allowed không thay local grant.
- DOCUMENT_SHARE/MANAGE không cấp quyền từ ADMIN moderation hoặc role token stale.
- Dependency timeout/down trả fail-closed; no cache fallback.
- Trace request ID không log token/payload nhạy cảm.
- Adapter migration tests chứng minh GET legacy và POST CORE-T03 cùng policy trong giai đoạn chuyển tiếp.
- Notification legacy worker/service JWT target được kiểm contract riêng; không để Core key được coi như notification source identity.
