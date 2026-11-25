# DOC-00.4 — Tương thích Public và Internal API

**Nguồn thiết kế:** DOC-T03/T04, CORE-T03/T04, SYS-02 tại HEAD c7f56c722f421bf1df17f5a82f26a78682eb82be. Đây là target; chưa xác minh runtime. Các route dưới đây là target đã được duyệt ở mức contract; DTO/OpenAPI chi tiết, một số giới hạn và AI compatibility vẫn pending.

## 1. Public Document API

DOC-T03 liệt kê 16 operations. Hiện không có Document router trong Core hoặc service riêng; Web allowlist chỉ định nghĩa Core operations tại apps/web/src/lib/api/operations.ts. Vì vậy mọi endpoint dưới đây đều MISSING trong runtime hiện tại.

| Nhóm | Operations mục tiêu DOC-T03 | Hiện trạng |
|---|---|---|
| Thư viện | GET/POST /api/v1/documents | Không có route. |
| Nguồn | GET/PATCH/DELETE /api/v1/documents/{document_id} | Không có route. Delete dự kiến 202 và khóa truy cập ngay; cleanup async. |
| Phiên bản | POST/GET /api/v1/documents/{document_id}/versions; GET /.../versions/{version_id}; GET /.../download | Không có route; Web live upload/download không khả dụng. |
| Chia sẻ | POST/GET /api/v1/documents/{document_id}/grants; DELETE /api/v1/documents/{document_id}/grants/{grant_id} | Không có route. |
| Lớp | GET /api/v1/classrooms/{classroom_id}/documents | Không có route. |
| Job | GET/POST /api/v1/documents/{document_id}/versions/{version_id}/jobs; GET /.../jobs/{job_id} | Không có route hoặc durable Document job store. |

DOC-T03 target status semantics gồm upload 201 sau khi file bền vững và DB transaction tạo version/job; retry 202; revoke 204; DELETE document 202; pagination 20/100. Kích thước 50 MB, format, frontend poll interval, admin/co-teacher/transfer và exact DTO/OpenAPI chưa được xác nhận đầy đủ. Không xem các route cũ trong FRS/TASK-017 là hợp đồng: FRS ghi chúng là endpoint tham khảo chưa duyệt (docs/architect/lumi-design/04_FRS_Document.md phần 8).

## 2. Internal Document–AI API

| Operation mục tiêu DOC-T04 | Bên sở hữu | Hiện trạng |
|---|---|---|
| POST /internal/v1/ingestion-jobs; trả 202 chỉ sau durable acceptance, idempotency key | AI nhận; Document khởi tạo | Không có AI service/API. |
| GET /internal/v1/ingestion-jobs/{ai_job_id} | AI | Không có. Worker RAG không expose HTTP status. |
| DELETE /internal/v1/documents/{document_id}/indexes và GET deletion job | AI thực thi; Document điều phối | Không có index deletion API/production lifecycle. |
| GET /internal/v1/versions/{version_id}/file | Document | Không có internal file API/stream. |
| GET /internal/v1/classrooms/{classroom_id}/rag-scope | Document | Không có grants/version scope API. |
| POST /internal/v1/rag-scope/validate | Document | Không có thu hồi/response-time validation API. |
| POST /internal/v1/authorization/check | Core theo CORE-T03 | Code hiện gần nhất là GET /internal/v1/classes/{class_id}/access với X-Service-Key và action legacy; chưa khớp route/verb/DTO/auth. |

RAG retrieval nhận callback authorize, nhưng caller chưa tồn tại trong repo; callback lấy tập source IDs không tương đương Core membership + Document grants đầy đủ. Cần giữ fail-closed, kiểm tra source scope trước retrieval và trước trả kết quả.

## 3. Internal authentication và compatibility

- Code hiện tại dùng X-Service-Key/scope core:check_access tại app/common/auth_dependencies.py:86–96; đây là implementation legacy cần chuyển theo foundation.
- Classroom router dùng prefix /internal/v1 và bảo vệ GET /classes/{id}/access ở router.py:60–63, 482–493.
- Action enum của Core có read_document_source và use_ai_tutor; đây là khả năng tương thích ở tầng quyền lớp, không cấp Document grant.
- SYS-02/CORE-T04 đặt Service JWT làm foundation chung; Document chỉ dùng verifier/client của foundation này, không tự tạo issuer hoặc key management. Foundation chưa được xác minh trong code.
- API public Core dùng /api/v1, UUID, Bearer access token, correlation_id/X-Correlation-ID theo core/API_CONTRACT.md:8–12. DOC-T03 target error envelope ghi request_id; hai trường cần thống nhất trước khi Web decoder được mở rộng.

## 4. Frontend routing / API proxy

- apps/web/src/lib/api/operations.ts ghi rõ allowlist chỉ gồm Core operations; không có document/tutor endpoints.
- apps/web/src/lib/data/integrations.ts:11–13 đánh dấu document/tutor/learning pending-contract.
- apps/web/src/lib/data/live.ts:29–57 trả 503 cho thao tác Document live. UI route được cung cấp qua data adapter, nhưng không có API path để tạo persistence.
- apps/web/src/lib/route-availability.ts cho phép một số route ở mock; mock mode không phải production integration.

## 5. Các điểm cần contract review trước implementation

1. Chốt schema OpenAPI cho 16 Public operations, exact DTO, pagination/cursor, error envelope và authorization semantics.
2. Đối chiếu 50 MB/5 formats với parser/AI team; chốt backend MIME sniffing, zip bomb/quarantine và rejection codes.
3. Chốt Service JWT claims/key rotation tương thích với Core; thay đổi cả Core consumer interface và Document/AI caller theo contract.
4. Chốt idempotency: key scope/lifetime, replay, 409 với payload khác; job retry sau terminal failure phải tạo execution mới theo DOC-T02/T05.
5. Chốt X-Request-ID/X-Correlation-ID propagation và redaction; không expose RAG trace/raw generation fields.
6. Chốt exact index_ready meaning, version identity, delete job and stale-result semantics với AI team.
7. Thêm API allowlist/proxy operations chỉ sau khi endpoint/schema/error tests có thể xác minh.

## 5. CORE-T03 adapter và gateway

CORE-T03 target là POST /internal/v1/authorization/check(user_id, resource_type, resource_id, action). Core xác minh user ACTIVE và membership/role; Document vẫn kiểm tra quyền tài nguyên của mình. Adapter gọi REST qua shared Service JWT, không import Core repository. Mapping legacy READ_DOCUMENT_SOURCE sang DOCUMENT_READ/SHARE/MANAGE chưa được chứng minh; fail closed cho tới khi contract/action semantics khớp.

System gateway inventory đề xuất route documents → Document và chặn /internal/*. Route/method/prefix rewriting chưa được triển khai hoặc xác minh. Core emits user.deletion_requested per target; Notification event 202 chỉ ACK bền vững, không phải deletion completion.
