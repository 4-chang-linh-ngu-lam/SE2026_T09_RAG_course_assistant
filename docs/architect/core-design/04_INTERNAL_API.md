# Internal API — CORE-T03/T06 sau CORE-CR03

Service JWT theo shared foundation SYS-02/CORE-T04; khác User JWT, có issuer/audience/scope/expiry/source identity; internal route không public.

## Authorization — CORE-T03

Target POST /internal/v1/authorization/check nhận user_id, resource_type, resource_id, action → allowed. Core kiểm user ACTIVE và current membership/teaching assignment/action; service sở hữu resource bổ sung kiểm tra owner/grant/version/assignment. Fail closed.

Actions: DOCUMENT_READ, DOCUMENT_SHARE, DOCUMENT_MANAGE, AI_QUERY, PRACTICE_ACCESS, ASSIGNMENT_CREATE, ASSIGNMENT_SUBMIT, ASSESSMENT_MANAGE, GRADE_MANAGE, ANALYTICS_VIEW. Mapping với ClassAccessAction cũ theo CORE-CR03; action không rõ/chưa map phải deny.

Giữ GET /internal/v1/classes/{class_id}/access + X-Service-Key trong migration window với chính sách legacy hiện tại. GET và POST mới dùng chung policy helper; key legacy không được mở rộng và không fallback khi JWT trên route mới sai.

## Lookup và event boundary — CORE-T06

Internal lookup chỉ trả DTO tối thiểu theo Service JWT scope. Event envelope versioned, per-target delivery, dedup và outbox atomic với producer transaction.

Giữ event types từ producer hiện hành (ví dụ CLASS_ENROLLMENT_CHANGED, CLASS_TEACHERS_CHANGED, CLASS_STATUS_CHANGED) theo mapping contract được freeze với Notification. Không phát self-join hoặc owner_transferred. user.deletion_requested thuộc CORE-T08; durable ACK khác per-target completion.
