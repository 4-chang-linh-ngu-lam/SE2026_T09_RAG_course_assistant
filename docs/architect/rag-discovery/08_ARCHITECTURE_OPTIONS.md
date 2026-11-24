# 08 — Ranh giới service: phương án và trade-off

## Option A — RAG là thư viện nội bộ của AI Service

AI Service sở hữu Tutor endpoints, conversation/message state, query orchestration và gọi services/rag như Python library. Document sở hữu file gốc/version/grant/lifecycle. AI sở hữu index/retrieval metadata dẫn xuất. Document có thể gọi IDP/chunking library hoặc chuyển canonical/versioned source qua một contract được duyệt.

**Ưu điểm:** phù hợp ADR-001 (năm services); không tạo network boundary thứ sáu; AI kiểm soát quyền riêng tư hội thoại và phối hợp Core/Document/Learning trước query. Các callable RAG hiện có có thể tái sử dụng nếu adapter dữ liệu và auth được chốt.

**Nhược điểm:** AI phải đóng gói RAG/model artifacts; cần cơ chế cập nhật/invalidate index khi Document đổi version/revoke grant; cần database riêng cho hội thoại.

**Service impact:** Web/API entry → AI; AI → Core access, Document grants/source, Learning D6; AI owns derived index/conversations.

**Đánh giá:** KHUYẾN NGHỊ, nhưng chưa được chốt API/model/storage.

## Option B — RAG thành microservice thứ sáu

Tách ingestion/index/retrieval/generation thành một service HTTP riêng và để AI Service gọi RAG.

**Ưu điểm:** có thể scale CPU/GPU và retrieval độc lập khỏi conversation API.

**Nhược điểm:** architecture hiện chốt năm services; thêm service làm trùng auth/trace/retry/model deployment, tăng boundary giữa AI và RAG nhưng code hiện chưa có HTTP app, DB, index store hay health checks. Việc ai sở hữu index/grant/revocation còn phải phân xử.

**Service impact:** thêm RAG service, service credential, network/API contract, storage, deploy/runtime/monitoring và data boundary thứ sáu.

**Đánh giá:** KHÔNG KHUYẾN NGHỊ nếu chưa có nhu cầu scaling đo được.

## Option C — Document sở hữu ingestion worker; AI sở hữu query/index

Document Service tiếp nhận upload, version, grant, xử lý trạng thái. Worker Document gọi IDP/chunking như library để tạo canonical; AI nhận source version được phép và quản lý index dẫn xuất/retrieval. Mỗi query AI kiểm grant hiện hành từ Document và D6 từ Learning.

**Ưu điểm:** source-of-truth và revoke ở Document; index/citation derive ở AI; khớp ownership ARCHITECTURE.

**Nhược điểm:** cần contract giao canonical/source text/version, trigger index, retry/activation và cache invalidation. Current Canonical v2 publisher path chưa khép kín.

**Service impact:** Document APIs/jobs/events; AI index lifecycle; Core school/class scope; Learning D6.

**Đánh giá:** KHUYẾN NGHỊ kết hợp với Option A; chưa chọn broker, blob store hay event schema.

## Option D — Duy trì offline library/evaluation

Tiếp tục test RAG bằng local corpus/fixtures và callable Python interfaces, chờ Document/AI/Learning contracts.

**Ưu điểm:** không tạo risk Production privacy, model, storage hoặc auth; hiện là trạng thái kiểm chứng thực tế tốt nhất.

**Nhược điểm:** không có Tutor live endpoint, không thể test dữ liệu Production hoặc user journey.

**Service impact:** không thêm runtime; chỉ có CI/local harness.

**Đánh giá:** HIỆN TRẠNG; dùng làm baseline cho đến khi contracts/ops decisions được chốt.

## Khuyến nghị của khảo sát

Giữ năm microservices theo ADR-001. Xây AI Service làm biên deployable cho hội thoại/Tutor; dùng RAG nội bộ như library. Để Document giữ file/version/grant và khởi tạo processing; AI giữ index dẫn xuất và kiểm grant mới mỗi query. Learning là authority cho D6. Chưa tách RAG thành service riêng và chưa chọn công nghệ queue/vector store/cloud model khi chưa có yêu cầu đo được.
