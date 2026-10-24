# TASK-017: Document Service Specification & Implementation (G3)

- **Mã Task:** `TASK-017`
- **Giai đoạn:** `G3 — Document + AI`
- **Owner chính:** Phụ trách Service Document
- **Business Rules liên quan:** `B1`, `B2`, `B3`, `B4`, `B5`, `B6`, `B7`, `H3`, `H6`, `L6`, `O1`, `O2`, `G5`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#b-tài-liệu), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md#2-ownership), [ADR-001](../docs/architect/microservices-v1/ADR-001.md)

## Rà soát đồng bộ — 2026-10-16

**Cập nhật 2026-10-23:** người dùng đã duyệt toàn bộ gói Document v1; service và sáu workspace Web đã triển khai. Phần nháp lịch sử bên dưới không còn là wire contract; dùng [API v1](../docs/architect/microservices-v1/document/API_CONTRACT.md) với trạng thái `READY`, [thiết kế](../docs/architect/microservices-v1/document/DESIGN.md), [events](../docs/architect/microservices-v1/document/EVENT_CONTRACT.md) và [bằng chứng kiểm thử thực tế](../apps/web/docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md). Owner sign-off và KPI/QAS vẫn cần nghiệm thu riêng.

**Hiện trạng:** chưa có service Document. Model/enum/route cụ thể bên dưới chỉ là bản nháp tham khảo, chưa phải thiết kế hoặc API được duyệt; không áp đặt stack/storage/queue từ task này.

**Cần sửa/bổ sung:**
- Chỉ triển khai sau nghiệm thu Core G1/G2; trước code chốt thiết kế/API/event contracts với TASK-008/012/018, service credential và scope. Không truy cập SQL Core hoặc coi metadata môn/khối là quyền.
- Bổ sung bookmark bên cạnh SourceBoundNote; owner-only và lịch sử cá nhân tách khỏi participation. ARCHIVED cho sửa notes/bookmarks với nguồn còn quyền (O2); source revoke vẫn giữ chữ tự viết nhưng che quote/open-source.
- Xác minh assignment PRIMARY/ASSISTING và grant hiện hành ở chia sẻ/xem/tải; ASSISTING không sửa/xóa file nguồn của người khác. Cảnh báo trước xóa nguồn đang dùng ở nhiều lớp.
- Phiên bản chỉ được công bố sau xử lý thành công; retry/crash không mất file hoặc phát index dở; source revoke thắng fallback phiên bản cũ. AI index là dữ liệu dẫn xuất, Document sở hữu file/version/grant.
- 10 MB là tải mẫu TP-01, không phải giới hạn upload đã được chốt. Chốt hạn mức/validation, version event và thu hồi quyền trong thiết kế, không tự chọn broker/schema.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] Core G2, TASK-008 access contract và thiết kế Document được review; TV2/TV4 và owner AI thống nhất grant/retry/invalidation.
- [x] Test 5 định dạng, version fallback/crash, cross-school/class, revoke khi mở nguồn, owner-only notes/bookmarks và O2: backend +HTTP/browser fixtures trong báo cáo2026-10-23. AI retrieval nằm ngoài TASK-017 và chưa chứng nhận.
- [ ] Có contract tests và bằng chứng QAS-04/QAS-10; không coi bản nháp route/model dưới đây là phần đã triển khai.

---

## 1. Mục tiêu
Thiết kế và triển khai Document Service (`services/document/`) độc lập trong monorepo, quản lý thư viện tài liệu cá nhân của Giảng viên, hỗ trợ 5 định dạng tệp, quản lý đa phiên bản, chia sẻ tài liệu cho lớp học (`ClassDocumentGrant`), xử lý tài liệu bất đồng bộ và quản lý ghi chú/bookmark gắn nguồn.

---

## 2. Bản nháp kỹ thuật — cần thiết kế và review trước triển khai

### 2.1. Mô hình dữ liệu tham khảo — chưa chốt schema vật lý
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
- **5 định dạng (Rule B3):** Hỗ trợ tệp PDF, PPTX, DOCX, TXT và Markdown TP-01 dùng tệp trung bình 10 MB để đo tải; giới hạn upload còn phải thiết kế.
- **Đa phiên bản (Rule B4, H3):** Lớp học luôn sử dụng phiên bản mới nhất đã xử lý thành công (`SUCCESS`). Nếu phiên bản mới bị lỗi (`FAILED`), hệ thống tiếp tục dùng phiên bản thành công gần nhất, hiển thị thông báo lỗi và cho phép giảng viên thử lại (`retry`).
- **Phân quyền chia sẻ (Rule B2, O1):** Giảng viên chính và đồng giảng viên được thêm/gỡ chia sẻ tài liệu trong lớp, nhưng chỉ chủ sở hữu tài liệu nguồn mới có quyền sửa/xóa tệp gốc hoặc các phiên bản.
- **Thu hồi quyền (Rule B6, B7):** Khi giảng viên thu hồi chia sẻ tài liệu khỏi lớp, quyền truy cập của sinh viên bị chấm dứt ngay lập tức; RAG không được phép truy hồi từ tài liệu này nữa.
- **Xác thực quyền lớp:** Document Service dự kiến gọi endpoint Core `/internal/v1/classes/{class_id}/access` để xác minh quyền giảng viên và sinh viên trước khi cho phép tải/xem tài liệu.

### 2.3. Endpoint tham khảo — chưa phải API Contract được duyệt
- Quản lý tài liệu: `POST /documents`, `POST /documents/{id}/versions`, `POST /documents/{id}/retry-processing`.
- Chia sẻ lớp: `POST /classes/{class_id}/documents/grant`, `DELETE /classes/{class_id}/documents/grant/{doc_id}`.
- Ghi chú: `GET/POST /classes/{class_id}/notes`, `PATCH/DELETE /notes/{id}`.
- Internal check: `GET /internal/v1/classes/{class_id}/documents/active-grants` phục vụ AI Service truy hồi.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria)
- [x] Tải lên thành công cả 5 loại định dạng (PDF, PPTX, DOCX, TXT, MD) và kích hoạt tiến trình bóc tách nội dung. PostgreSQL/container tests thực chạy trong báo cáo2026-10-23.
- [x] Thử nghiệm lỗi phiên bản: Upload phiên bản v2 bị lỗi $\to$ Lớp học vẫn đọc được nội dung phiên bản v1 (Rule H3).
- [x] Thu hồi chia sẻ: Giảng viên gỡ chia sẻ $\to$ Sinh viên gọi API đọc tài liệu lập tức bị từ chối `403 FORBIDDEN` (Rule B6).
- [x] Sinh viên xem ghi chú cá nhân khi tài liệu bị gỡ chia sẻ: Vẫn đọc được chữ tự viết nhưng nội dung trích dẫn từ tài liệu bị che lại (Rule H6/L6).
