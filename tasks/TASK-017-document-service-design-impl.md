# TASK-017: Document Service Specification & Implementation (G3)

- **Mã Task:** `TASK-017`
- **Giai đoạn:** `G3 — Document + AI`
- **Owner chính:** Phụ trách Service Document
- **Business Rules liên quan:** `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `H3`, `H6`, `L6`, `O1`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#b-tài-liệu), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership), [ADR-001](../docs/architect/microservices-v1/ADR-001.md)

---

## 1. Mục tiêu
Thiết kế và triển khai Document Service (`services/document/`) độc lập trong monorepo, quản lý thư viện tài liệu cá nhân của Giảng viên, hỗ trợ 5 định dạng tệp, quản lý đa phiên bản, chia sẻ tài liệu cho lớp học (`ClassDocumentGrant`), xử lý tài liệu bất đồng bộ và quản lý ghi chú/bookmark gắn nguồn.

---

## 2. Chi tiết kỹ thuật

### 2.1. Sở hữu dữ liệu & Mô hình lưu trữ (Schema `document`)
- `Document`: Quản lý tài liệu nguồn thuộc sở hữu giảng viên (`owner_user_id`), tiêu đề, mô tả.
- `DocumentVersion`:
  - `id: UUID`, `document_id: UUID`, `version_number: int`, `file_path: str`
  - `file_type: Enum` (`PDF`, `PPTX`, `DOCX`, `TXT`, `MARKDOWN`)
  - `file_size_bytes: int`
  - `processing_status: Enum` (`PENDING`, `PROCESSING`, `SUCCESS`, `FAILED`)
  - `error_message: Optional[str]`
  - `created_at: datetime`
- `ClassDocumentGrant`:
  - `id: UUID`, `class_id: UUID`, `document_id: UUID`, `granted_by: UUID`
  - `is_active: bool` (Rule B6: Thu hồi chia sẻ có hiệu lực tức thì)
- `SourceBoundNote`:
  - `id: UUID`, `user_id: UUID`, `class_id: UUID`, `document_version_id: UUID`
  - `page_or_slide: Optional[str]`, `note_content: str`, `quote_text: Optional[str]`
  - Quy tắc: Giữ ghi chú tự viết nhưng che đoạn trích dẫn nguyên văn khi tài liệu bị thu hồi (Rule H6, L6).

### 2.2. Các quy tắc nghiệp vụ bắt buộc
- **5 định dạng (Rule B3):** Hỗ trợ tệp PDF, PPTX, DOCX, TXT và Markdown dung lượng trung bình 10MB (theo cấu hình TP-01).
- **Đa phiên bản (Rule B4, H3):** Lớp học luôn sử dụng phiên bản mới nhất đã xử lý thành công (`SUCCESS`). Nếu phiên bản mới bị lỗi (`FAILED`), hệ thống tiếp tục dùng phiên bản thành công gần nhất, hiển thị thông báo lỗi và cho phép giảng viên thử lại (`retry`).
- **Phân quyền chia sẻ (Rule B2, O1):** Giảng viên chính và đồng giảng viên được thêm/gỡ chia sẻ tài liệu trong lớp, nhưng chỉ chủ sở hữu tài liệu nguồn mới có quyền sửa/xóa tệp gốc hoặc các phiên bản.
- **Thu hồi quyền (Rule B6, B7):** Khi giảng viên thu hồi chia sẻ tài liệu khỏi lớp, quyền truy cập của sinh viên bị chấm dứt ngay lập tức; RAG không được phép truy hồi từ tài liệu này nữa.
- **Xác thực quyền lớp:** Document Service gọi endpoint Core `/internal/v1/classes/{class_id}/access` để xác minh quyền giảng viên và sinh viên trước khi cho phép tải/xem tài liệu.

### 2.3. Endpoint & Xử lý bất đồng bộ
- Quản lý tài liệu: `POST /documents`, `POST /documents/{id}/versions`, `POST /documents/{id}/retry-processing`.
- Chia sẻ lớp: `POST /classes/{class_id}/documents/grant`, `DELETE /classes/{class_id}/documents/grant/{doc_id}`.
- Ghi chú: `GET/POST /classes/{class_id}/notes`, `PATCH/DELETE /notes/{id}`.
- Internal check: `GET /internal/v1/classes/{class_id}/documents/active-grants` phục vụ AI Service truy hồi.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [ ] Tải lên thành công cả 5 loại định dạng (PDF, PPTX, DOCX, TXT, MD) và kích hoạt tiến trình bóc tách nội dung.
- [ ] Thử nghiệm lỗi phiên bản: Upload phiên bản v2 bị lỗi $\to$ Lớp học vẫn đọc được nội dung phiên bản v1 (Rule H3).
- [ ] Thu hồi chia sẻ: Giảng viên gỡ chia sẻ $\to$ Sinh viên gọi API đọc tài liệu lập tức bị từ chối `403 FORBIDDEN` (Rule B6).
- [ ] Sinh viên xem ghi chú cá nhân khi tài liệu bị gỡ chia sẻ: Vẫn đọc được chữ tự viết nhưng nội dung trích dẫn từ tài liệu bị che lại (Rule H6/L6).
