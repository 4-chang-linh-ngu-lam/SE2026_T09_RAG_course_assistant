# Lumi RAG — Biên bản Technical Lead Review 01

**Trạng thái:** RAG-D01 ACCEPTED / CÁC CONTRACT CHI TIẾT PENDING  
**Source commit:** `2d975514c4d017fe135b38df13652714b33433eb` (`codex/rag-technical-discovery`)  
**Nguồn:** `docs/architect/rag-discovery/00..09`, `docs/architect/microservices-v1/ADR-001.md`, `docs/architect/microservices-v1/ARCHITECTURE.md`, `docs/architect/BUSINESS_RULES.md`, `services/rag/README.md`.

## Đã xác minh từ 10 tài liệu discovery

- `services/rag` là pipeline Python offline với các stage IDP, chunking, indexing, retrieval, packing, generation và citations; chưa có HTTP API hoặc AI Service triển khai.
- Canonical emitter hiện dùng `idp-canonical-1`; đường v2 được mô tả nhưng `idp.publish` không có trong repository được khảo sát. Chưa có adapter production version-bound Canonical → TextDocument → index.
- Index chính hiện là immutable filesystem bundles và vectors nạp RAM; không có active version pointer, source grant ownership hoặc multi-instance lifecycle.
- Retrieval yêu cầu caller-provided authorization callback; callback chưa nối với Core/Document; việc kiểm tra lại trước trả answer đã có trong engine nhưng không thay thế quyền thực tế.
- Các kiểm thử CI 144 passed, 2 skipped, 1 xfailed dựa vào fixtures; không chứng minh inference model thật hoặc RAG end-to-end Production.
- AI Tutor chưa có conversation storage và Learning D6/Document active-grant API.
- Rủi ro bảo mật: trace nội bộ có raw generation text, không được expose/log qua public HTTP adapter; locator/citation hiện chưa phải Document-facing DTO hoàn chỉnh.

## Kết luận review

Các báo cáo phù hợp để làm tài liệu khảo sát và lập danh sách rủi ro; chúng **không phải approved implementation/API contract**. Không tự đổi trạng thái của `09_OPEN_DECISIONS.md` thành ACCEPTED.

## ADR-001 và ranh giới đã duyệt (RAG-D01)

**Ranh giới được duyệt (RAG-OD-01):** Giữ 5 microservices như ADR-001. `services/rag` là Python library/engine được AI Service sử dụng cho index/query/generation, không mở thêm RAG microservice thứ sáu.

**Ranh giới sở hữu được duyệt (RAG-OD-01 và RAG-OD-03):** Document Service sở hữu upload/source files/DocumentVersion/class grants/revocation/processing jobs; có thể sử dụng `idp`/chunking như Python library trong worker của chính Document. AI Service sở hữu conversation/message, derived search index và Tutor orchestration, gọi Core current classroom access, Document current grants/versions, Learning official assessment D6. Mọi truy hồi phải fail closed khi chưa kiểm chứng quyền.

**Chưa chốt:** ranh giới thực thi embedding/indexing, chuẩn canonical adapter, API endpoints, storage, event contract, inference provider, model runtime và chính sách vận hành.

**Lưu ý:** RAG engine không cần và không nên tự tin tưởng `source_acl` trong Canonical; gateway/service layer phải cấp đúng authorized child IDs từ quyền Core + Document hiện hành.

## Câu hỏi để Product Owner phê duyệt — RAG-D01

Có đồng ý giữ RAG là thư viện nội bộ của **AI Service** (không thêm service thứ sáu) và để **Document Service sở hữu file/version/grant/ingestion**, còn **AI Service sở hữu retrieval/index dẫn xuất/generation/conversation**, theo ADR-001 hay không?

- A — Đồng ý khung ranh giới này (khuyến nghị Technical Lead; các contract chi tiết vẫn PENDING).
- B — Muốn RAG thành microservice HTTP riêng (cần giải trình thay đổi ADR-001 và chi phí vận hành).
- C — Chưa chốt; cần đánh giá thêm.

**Trạng thái quyết định:** ACCEPTED — Phương án A.

**Ngày phê duyệt:** 25/11/2026 (Product Owner).

**Phạm vi:** Chấp thuận ranh giới sở hữu và mô hình 5 microservices; không thêm RAG service thứ sáu. Các contract chi tiết và quyết định mở trong discovery vẫn cần review riêng; không phải phê duyệt triển khai hoặc deploy.

## Các quyết định tiếp theo

1. Canonical v1/v2 và adapter giữ page/block locator.
2. Lifecycle index/version activation/reindex/delete; Document→AI event contract.
3. Core/Document/Learning current-access checks và query-time authorization.
4. AI HTTP API: Tutor turns, retrieve-only internal operations, history/streaming.
5. Model provider/runtime, test evidence, privacy, retention 14 ngày chat/tạm/log theo quyết định Product Owner trước đó (chưa đồng bộ vào GitHub ADR).

## Giới hạn review

Đã đọc đầy đủ 10 Markdown discovery và đối chiếu tài liệu nguồn chuẩn. Chưa chạy mã hay test mới, chưa xác minh remote Production runtime. Đây là biên bản kiến trúc, không phải nghiệm thu thực thi.

## Điều chỉnh phạm vi thiết kế — 25/11/2026 (ACCEPTED)

- Product Owner phụ trách Core, Document, Learning, Notification và tích hợp toàn hệ thống.
- Nhóm AI/RAG phụ trách AI Service và RAG Engine; Product Owner hỗ trợ endpoint/adapter tích hợp khi cần.
- RAG-D01 giữ ACCEPTED. RAG-D02 (Canonical v1/v2) DEFERRED, giao nhóm AI/RAG quyết định nội bộ; hợp đồng dữ liệu liên service vẫn cần hai bên thống nhất.
- Thứ tự review tiếp theo: Document–AI integration contract; authorization Core/Document/AI; Learning–AI; lifecycle tài liệu/index; public API/frontend; lỗi/retry/timeout; integration tests/deployment.
- Không phê duyệt trước các contract hoặc thuật toán chưa được thảo luận.

## DOC-D01 — Ranh giới xử lý tài liệu (ACCEPTED)

**Phương án A — Document quản lý, AI xử lý nội dung.** Product Owner phê duyệt ngày 25/11/2026.

- Document Service sở hữu file gốc, metadata, DocumentVersion, grants/revocation, kiểm tra upload, điều phối ingestion jobs và theo dõi trạng thái xử lý; yêu cầu AI xử lý hoặc xóa index khi cần.
- AI Service sở hữu thực thi trích xuất/OCR/Canonical/chunking/embedding/indexing và dữ liệu index dẫn xuất; báo cáo kết quả xử lý cho Document.
- Quyết định này cụ thể hóa RAG-D01: Document sở hữu nghiệp vụ ingestion, AI thực thi pipeline nội dung. Đề xuất trước đây về thực thi IDP/chunking trong Document worker không được chọn cho phạm vi này.
- Canonical v1/v2 và thuật toán nội bộ vẫn thuộc nhóm AI/RAG (RAG-D02 DEFERRED). Giao thức REST/queue, schema, retry, idempotency, activation và authorization contract vẫn PENDING.

## DOC-D02 — Cơ chế giao tiếp Document–AI (ACCEPTED)

**Phương án B — REST API bất đồng bộ cho Increment 1.** Product Owner phê duyệt ngày 25/11/2026.

- Document gửi yêu cầu xử lý; AI trả HTTP 202 Accepted cùng job ID sau khi tiếp nhận bền vững, xử lý pipeline bất đồng bộ.
- Job phải bền vững qua restart, hỗ trợ idempotency và retry; Document vẫn hoạt động khi AI offline, không đánh dấu READY khi chưa xác minh index đúng phiên bản và đủ điều kiện kích hoạt.
- Không bổ sung message broker cho tích hợp này trong Increment 1; giữ khả năng chuyển đổi sau này. Không coi FastAPI BackgroundTasks đơn thuần là cơ chế job bền vững.
- Polling/callback, worker runtime, endpoint/schema cụ thể, retry policy, authorization và activation contract vẫn PENDING; nhóm AI/RAG sở hữu thực thi nội bộ.

## DOC-D03 — Đồng bộ trạng thái xử lý (ACCEPTED)

**Phương án A — Polling cho Increment 1.** Product Owner đồng ý ngày 25/11/2026.

- Document Service chủ động polling trạng thái job qua internal REST API của AI; không phụ thuộc trình duyệt, lưu trạng thái bền vững và phục hồi sau restart.
- Hỗ trợ backoff khi lỗi hoặc job kéo dài; xác minh job/version và điều kiện activation trước READY. Không coi lỗi kết nối là kết quả xử lý thất bại.
- Không yêu cầu callback trong Increment 1; có thể nâng cấp Hybrid sau này. Chu kỳ polling, scheduler, endpoint/schema và retry policy cụ thể vẫn PENDING.

## DOC-D04 — Vòng đời và trạng thái tài liệu (ACCEPTED)

**Phương án B — Tách trạng thái theo trách nhiệm.** Product Owner đồng ý ngày 25/11/2026.

- Tách vòng đời Document, trạng thái lưu file DocumentVersion và trạng thái thực thi IngestionJob; không gộp thành một status chung.
- Trạng thái dự kiến: Document ACTIVE/DELETING/DELETED; DocumentVersion UPLOADING/STORED/FAILED; IngestionJob PENDING/PROCESSING/SUCCEEDED/FAILED. Tên enum và schema cụ thể vẫn PENDING.
- AI lỗi không làm mất khả năng quản lý/tải file đã lưu nếu quyền hiện hành cho phép. Retry bảo toàn lịch sử thực thi; SUCCEEDED không đồng nghĩa index đã activation.
- Query chỉ được phép với phiên bản/index hợp lệ đã kích hoạt và quyền hiện hành; chính sách version activation, reindex, deletion và authorization chi tiết vẫn PENDING.
