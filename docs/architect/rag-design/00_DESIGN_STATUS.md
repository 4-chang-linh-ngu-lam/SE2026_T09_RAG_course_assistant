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
