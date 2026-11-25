# DOC-00.6 — Security và resilience

## 1. Bản đồ trust boundary

| Bên | Trách nhiệm được duyệt | Bằng chứng hiện tại | Kết quả |
|---|---|---|---|
| Core | Identity, membership, lớp, quyền sử dụng AI và class action | GET internal class access; action read_document_source/use_ai_tutor | Có nền tảng class authorization, thiếu Document grant integration. |
| Document | Source file, owner, version, class grants/revoke, ingestion state | Chưa có service | Thiếu hoàn toàn. |
| AI Service | Tutor conversation, orchestration, derived index và gọi RAG | Chưa có services/ai | Thiếu hoàn toàn. |
| RAG Engine | Library xử lý, index/retrieval/generation; không tự cấp quyền | Callback authorize bắt buộc, output grants_authorization=false | Thành phần offline, chưa được nối service. |
| Web | Gửi user intent qua adapter, không quyết định quyền | Live Document methods trả 503 | Không thể là authorization source hoặc backend. |

Nguyên tắc nguồn: docs/architect/microservices-v1/ARCHITECTURE.md:36–40; DOC-D06 và DOC-T04 tại design status commit 8d1015c. Business Rules B1–B7, H3/H6, L2/L6 và O1 yêu cầu quyền theo lớp/tài nguyên hiện hành, giữ phiên bản dùng được khi phiên bản mới lỗi, chặn truy cập sau revoke và giới hạn quyền giáo viên.

## 2. Authorization

- Request user phải được xác thực ở Core; Document không tin user_id/role/class/document IDs do browser tự gửi.
- Core kiểm tra class membership/action; Document kiểm tra ownership/grant/version của mình. Không thay Document grants bằng Core membership hoặc metadata trong index.
- RAG retrieval yêu cầu caller trả tập authorized source IDs; local source_acl là metadata, không phải nguồn quyền. Nếu Core/Document không khả dụng, consumer phải fail closed.
- Revoke phải có hiệu lực với query mới trước khi index được dọn. DOC-D06 yêu cầu kiểm tra trước retrieval và trước khi trả kết quả; streaming race sau khi dữ liệu đã gửi phải được xác định trong contract.
- SYS-02/CORE-T04 là Service JWT foundation cấp hệ thống; code hiện tại còn X-Service-Key (auth_dependencies.py:86–96). Document không tự tạo issuer/key store; chỉ tích hợp verifier/client khi foundation sẵn sàng.
- Internal file endpoint phải bind document/version/job; file ID hoặc job ID giả mạo/out-of-scope phải từ chối, không để endpoint thành arbitrary file server.

## 3. Data minimization, citations và logs

- Architecture cấm log token, password, private chat hoặc nguyên văn tài liệu; AI Tutor chat thuộc ranh giới riêng của AI và Admin không được mặc định xem.
- RAG RagPipeline trace chứa raw_generation_text và primary_raw_generation_text (services/rag/pipeline.py:476–481). Adapter phải chọn trường allowlist và redact; không serialize nội bộ trace ra API/log.
- Citation hiện chưa là Document-facing DTO đủ trường ownership/version. API phải gắn document_id và version_id đúng nguồn; không coi citation locator là quyền mở file.
- Canonical source_acl có thể chứa owner/users/groups nhưng mặc định không công khai; dữ liệu này không chứng minh current grants và không thể thay lookup.
- Error response không lộ stack trace, file path, raw prompt, secret, filename nhạy cảm hoặc nội dung nguồn.

## 4. Resilience đã duyệt và khoảng trống

DOC-T05 xác định:

- durable PostgreSQL jobs; không thêm message broker chỉ cho ingestion Increment 1;
- exponential backoff + equal jitter, adaptive polling, circuit breaker, bounded concurrency, per-operation timeout;
- retry transport errors, 429/Retry-After và lỗi gateway theo budget; lỗi validation/permission dừng; 409 reconcile;
- resend giữ cùng job/idempotency key; timeout không kết luận remote thất bại; terminal confirmed failure mới cho execution mới;
- worker claim ngắn trong transaction, lease expiry, lease token/fencing và restart recovery;
- giá trị khởi điểm đề xuất 5s–300s backoff, polling 3s→30s, circuit mở sau 5 lỗi/30s cooldown, connect 3s, submit 10s, file download 120s, AI query 60s; quantitative tuning/benchmark chưa nghiệm thu.

Hiện tại RAG worker enqueue/claim/recover qua filesystem JSON/rename và local SQLite, không có shared queue/DB lease hay HTTP status. Core outbox/notification worker có ownership và semantics riêng; không nên tái sử dụng trực tiếp làm Document job queue. Chưa có Document worker, retry scheduler, circuit breaker, active concurrency limits hoặc stale-worker fencing cho AI.

## 5. Retention, delete và fail-safe

Business Rules và Lumi design để retention theo loại dữ liệu/policy ở trạng thái cần chốt. DOC-D04/D05 chốt một số trạng thái và version activation nhưng không phê duyệt retention pháp lý, thời hạn giữ bản cũ, hard-delete timing, backup erasure hoặc orphan cleanup chi tiết. Hệ quả:

- có thể thiết kế trạng thái DELETING và khóa truy cập ngay theo DOC-T03;
- chưa đủ căn cứ hoàn tất xóa vĩnh viễn file, index, backups và mọi derivative;
- xóa/revoke không được bỏ qua auth gate vì index cleanup bất đồng bộ;
- mọi operation xóa phải có audit/idempotency/reconciliation, nhưng lifecycle schedule cụ thể chờ quyết định.

## 6. Failure modes cần kiểm tra trong implementation

1. Core unavailable hoặc scope timeout: deny, không fallback sang cached roles/ACL.
2. Document grant revoked giữa retrieval và response: revalidate scope trước khi trả.
3. AI trả 202 rồi restart: Document giữ job pending và poll lại cùng remote job/key.
4. Duplicate submit/lost response: cùng key không tạo job thứ hai; payload khác trả conflict.
5. Lease hết hạn nhưng worker cũ quay lại: fencing token ngăn stale update/activation.
6. V2 processing/failed: giữ V1 active nếu còn grant/quyền hợp lệ.
7. File lưu được nhưng DB commit lỗi hoặc ngược lại: reconcile, không mất/đọc file mồ côi.
8. Delete trong khi ingest: index result đến muộn không hồi sinh tài liệu.

Các hành vi trên là acceptance target, không phải khả năng đã được xác minh trong runtime hiện tại.

## 7. Service JWT và distributed deletion

SYS-D05/SYS-02 và CORE-T04 xác định một trust foundation dùng chung; issuer, key distribution/rotation vẫn pending. Document là consumer và gọi CORE-T03; không phát JWT riêng hoặc dựa vào user JWT.

CORE-T06/T08 phát user.deletion_requested theo từng target. Document cần revoke ngay và bền vững theo dõi source/grant cleanup cùng AI index deletion; Notification chỉ nhận event. Per-target ACK khác completion. Retention, retry horizon, completion DTO, physical purge và backup erasure vẫn là blockers.
