# Internal API — CORE-T03/T06 sau CORE-CR03

Service JWT theo shared foundation SYS-02/CORE-T04; khác User JWT, có issuer/audience/scope/expiry/source identity. Internal route không public qua gateway.

## Authorization — CORE-T03

Đã triển khai class-scoped adapter:

`POST /internal/v1/authorization/check`

Request nghiêm ngặt: `{user_id: UUID, resource_type: "class", resource_id: UUID, action: AuthorizationAction}`. Response duy nhất: `{allowed: boolean}`. Không trả user, school, membership, teaching role hoặc class status. `resource_type` hiện chỉ nhận `class`; không kiểm tra hay giả lập quyền cho `document_id`, `assignment_id` hoặc resource thuộc database service khác.

Endpoint yêu cầu Service JWT audience `core`, scope `core:check_access` và caller/action allowlist:

| Caller service identity | Actions |
|---|---|
| `document` | DOCUMENT_READ, DOCUMENT_SHARE, DOCUMENT_MANAGE |
| `ai` | AI_QUERY |
| `learning` | PRACTICE_ACCESS, ASSIGNMENT_CREATE, ASSIGNMENT_SUBMIT, ASSESSMENT_MANAGE, GRADE_MANAGE, ANALYTICS_VIEW |
| Other/Notification | None |

Caller được phép gọi endpoint không mặc nhiên được gọi toàn bộ actions. Denied action caller trả 403; Service JWT thiếu/sai trả 401; trust config unavailable trả 503; invalid request/unknown action/resource type trả 422. Business permission deny trả 200 `{allowed:false}`; unknown/cross-school class cũng trả false để không lộ resource existence. Database failure trả non-success (503 cho SQLAlchemy errors); không trả allow khi không xác minh được quyền.

### Class-side action mapping

| Target action | Core class-side decision | Consumer vẫn phải kiểm tra |
|---|---|---|
| DOCUMENT_READ | Reuse READ_DOCUMENT_SOURCE: ACTIVE same-school user có current Student membership hoặc Lecturer teaching assignment; archived class chỉ là read path. | Document kiểm owner/grant/current successful version trước file/preview/retrieval. |
| DOCUMENT_SHARE | PRIMARY/ASSISTING assignment hiện hành và lớp ACTIVE. | Document kiểm owner/quyền share, source status, grant transaction/idempotency/audit. |
| DOCUMENT_MANAGE | PRIMARY/ASSISTING assignment hiện hành và lớp ACTIVE cho thao tác class-scoped. | Document xác minh source owner và quyền resource. Thao tác library/source không gắn lớp không gọi adapter này. |
| AI_QUERY | Reuse USE_AI_TUTOR: chỉ Student membership hiện hành trong lớp ACTIVE. Lecturer không được phép qua action này. | AI/Document kiểm grant, version, scope, retrieval source IDs và revalidation trước response. |
| PRACTICE_ACCESS | CORE04-D02-A: Student-only, ACTIVE user cùng trường và current Student membership trong lớp ACTIVE. Không reuse PARTICIPATE_CURRENT_CLASS vì predicate legacy cho phép Lecturer. | Learning kiểm chủ thể attempt, practice resource, deadline và result ownership. |
| ASSIGNMENT_CREATE | Assigned PRIMARY/ASSISTING Lecturer trong lớp ACTIVE. | Learning kiểm tạo nháp, assignment policy và resource; không cấp quyền submit. |
| ASSIGNMENT_SUBMIT | Chỉ Student membership hiện hành trong lớp ACTIVE. | Learning kiểm assignment, due time, attempt, recipient/version snapshot và idempotency. |
| ASSESSMENT_MANAGE | Assigned PRIMARY/ASSISTING Lecturer trong lớp ACTIVE. | Learning bắt buộc PRIMARY phê duyệt công bố Assessment chính thức và áp dụng transition/approval policy. |
| GRADE_MANAGE | Reuse GRADE_SUBMITTED_WORK: assigned PRIMARY/ASSISTING Lecturer trong lớp ACTIVE. | Learning kiểm submission/grader assignment, grade history, audit và PRIMARY approval trước publish. |
| ANALYTICS_VIEW | Student có membership history, Lecturer có current assignment, hoặc Admin cùng trường. | Learning áp dụng Student owner-only, Teacher class scope, Admin aggregate, suppression/export audit và historical policy. |

Các predicate Core đọc user status/role, school, membership, teaching assignment và class lifecycle hiện hành; không tin role claims từ token. `check_class_action` hiện tại được dùng lại cho các action tương thích. Custom class gates không được giả dạng MODERATE_CLASS_CONTENT hoặc MANAGE_CLASS_CALENDAR.

`allowed:true` chỉ là class-side gate. Document/Learning/AI phải kiểm tra quyền tài nguyên thuộc service mình; response Core không cấp grant/owner access.

### CORE04-D01-A — Learning approval dependency gate

Learning official approval flows phụ thuộc hai action Core riêng biệt: `ASSESSMENT_APPROVE` xác minh PRIMARY assignment hiện hành cho lớp ACTIVE/cùng trường; `GRADE_CORRECTION_APPROVE` xác minh PRIMARY cho grade correction nhạy cảm. Hai action này hiện DEFERRED, không có trong `AuthorizationAction`, OpenAPI hoặc caller allowlist. `ASSESSMENT_MANAGE` không thay thế approval Assessment chính thức; `GRADE_MANAGE` không thay thế grade-correction approval. ASSISTING không được approve thay PRIMARY. Learning không truy vấn Core DB; chưa triển khai các approval workflow tương ứng trước khi Core action có mặt và được verify.

### Error và fail-closed semantics

- 422: schema/UUID/resource type/action sai hoặc field thừa.
- 401: thiếu/sai/expired User JWT hoặc Service JWT trên route internal; route mới không nhận User JWT hay X-Service-Key.
- 403: scope thiếu hoặc service identity không được phép action đó.
- 200 + `allowed:false`: user/class không tồn tại trong scope, trạng thái/quyền lớp không đạt hoặc policy deny.
- 503: service auth/database dependency unavailable; không đổi lỗi dependency thành `allowed:true`.

### Legacy compatibility

Giữ nguyên `GET /internal/v1/classes/{class_id}/access` và X-Service-Key với action/response contract hiện tại. Không mở rộng scope/action của credential cũ; route mới chỉ Service JWT. Hai route dùng chung các predicate legacy thực sự tương đương; endpoint cũ không bị migrate hoặc xóa trong CORE-04.

## Lookup và event boundary — CORE-T06

Internal lookup chỉ trả DTO tối thiểu theo Service JWT scope. Event envelope versioned, per-target delivery, dedup và outbox atomic với producer transaction.

Giữ event types từ producer hiện hành (ví dụ CLASS_ENROLLMENT_CHANGED, CLASS_TEACHERS_CHANGED, CLASS_STATUS_CHANGED) theo mapping contract được freeze với Notification. Không phát self-join hoặc owner_transferred. user.deletion_requested thuộc CORE-T08; durable ACK khác per-target completion.
