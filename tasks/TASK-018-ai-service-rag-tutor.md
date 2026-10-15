# TASK-018: AI Service & Grounded RAG Tutor (G3)

- **Mã Task:** `TASK-018`
- **Giai đoạn:** `G3 — Document + AI`
- **Owner chính:** Phụ trách Service AI
- **Business Rules liên quan:** `C1`, `C2`, `C3`, `C4`, `C5`, `C6`, `D6`, `E5`, `F3`, `H4`, `H5`, `QAS-06`
- **Tài liệu căn cứ:** [BUSINESS_RULES.md](../docs/architect/BUSINESS_RULES.md#c-ai-tutor), [QUALITY_ATTRIBUTES.md](../docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md#qas-06--chất-lượng-rag-rag-quality), [ARCHITECTURE.md](../docs/architect/microservices-v1/ARCHITECTURE.md)

## Rà soát đồng bộ — 2026-10-16

**Hiện trạng:** chưa có AI Service/RAG. Model và schema bên dưới là draft cần thiết kế, chưa chốt provider/vector store/queue hoặc hợp đồng HTTP Document.

**Cần sửa/bổ sung:**
- Sau Core G2, chốt quyền action với TASK-008 và source/version/grant với TASK-017. Core allowed không thay Document grant; kiểm tra trước retrieval/prompt và khi mở citation, fail closed khi dependency lỗi.
- Tách quyền hỏi mới (lớp hiện hành + grant + assessment policy) và đọc lịch sử chat owner được phép sau transfer/archive. Không dùng membership ACTIVE làm điều kiện duy nhất cho mọi lần đọc.
- Chat riêng tư mặc định; chia sẻ một hội thoại cụ thể chỉ khi người dùng chủ động và theo contract được duyệt. Không thêm Admin read-all hoặc gửi nguyên văn chat qua audit/notification/analytics.
- Khi source bị thu hồi, giữ lịch sử hợp lệ nhưng che quote/nguồn không còn quyền; không truy hồi mới từ index stale. Phân biệt kiến thức chung, citation đáng tin và thiếu căn cứ.
- Triển khai đủ hỏi đáp nhanh/hướng dẫn từng bước phù hợp khối 6–12; hướng dẫn giáo viên không vượt policy hệ thống.
- TASK-019 sở hữu trạng thái Assessment; chốt hợp đồng chặn AI Tutor tích hợp khi làm bài chính thức trước tích hợp G4. Khi chưa có Learning, ghi pending cho E2E D6, không suy ra từ flag browser hoặc tuyên bố ngăn AI ngoài hệ thống.

**Phụ thuộc và nghiệm thu bổ sung:**
- [ ] Core G2 + Document contracts được review, quyền lịch sử/owner/source revoke/LOCKED/cross-school được kiểm thử.
- [ ] QAS-06 đo ít nhất 100 câu hỏi theo phương pháp đã duyệt; báo cấu hình/model và số liệu thật, không khẳng định KPI từ unit tests.
- [ ] Test hai chế độ, archive/transfer, grant revoke giữa pipeline, private-chat/share, fail-closed và QAS-01/02 cô lập lỗi.

---

## 1. Mục tiêu
Thiết kế và triển khai AI Service (`services/ai/`) độc lập trong monorepo, quản lý hội thoại AI Tutor, xây dựng pipeline Grounded RAG với cơ chế trích dẫn tài liệu tin cậy, kiểm tra quyền truy cập nguồn kép (Core + Document), và tuân thủ các quy tắc bảo mật riêng tư.

---

## 2. Bản nháp kỹ thuật — cần thiết kế và review trước triển khai

### 2.1. Mô hình dữ liệu tham khảo — chưa chốt schema vật lý
- `AIConversation`:
  - `id: UUID`, `user_id: UUID`, `class_id: UUID` (Hội thoại luôn gắn với 1 lớp cụ thể, Rule C5)
  - `mode: Enum` (`QUICK_QA`, `STEP_BY_STEP`, Rule C4)
  - `created_at`, `updated_at: datetime`
- `AIMessage`:
  - `id: UUID`, `conversation_id: UUID`, `role: Enum` (`USER`, `ASSISTANT`)
  - `content: str`, `citations_json: Optional[list]` (Chứa danh sách trích dẫn: doc_id, doc_name, page, slide)
  - `grounded: bool` (Đánh dấu câu trả lời có dựa trên tài liệu lớp hay kiến thức ngoài)
  - `created_at: datetime`
- `VectorIndexMetadata`: Lưu metadata mapping chunk vector với `document_version_id` và `class_id`.

### 2.2. Các quy tắc nghiệp vụ bắt buộc
- **Grounded RAG (Rule C1, C2, C3):**
  - RAG ưu tiên căn cứ từ tài liệu của lớp. Nếu dùng thêm kiến thức chung phải phân biệt rõ ràng.
  - Bắt buộc trích dẫn tên tài liệu và vị trí trang/slide/mục cụ thể khi có căn cứ tin cậy.
  - Khi tài liệu không chứa câu trả lời: **Nói rõ thiếu căn cứ, tuyệt đối không bịa đặt trích dẫn**.
- **Kiểm tra quyền truy cập kép (Rule B7, C5, QAS-04):**
  - AI Service trước khi truy hồi phải:
    1. Gọi Core Service `/internal/v1/classes/{class_id}/access` để xác minh quyền hỏi AI mới theo action/lớp/trường hiện hành; đọc lịch sử dùng quyền riêng.
    2. Theo contract Document cần duyệt (route tham khảo `/internal/v1/classes/{class_id}/documents/active-grants`) để lấy danh sách các tài liệu đang được cấp quyền hợp lệ cho lớp đó.
    3. Bộ lọc vector retrieval **chỉ tìm kiếm trong phạm vi các tài liệu đang có grant hợp lệ**. Không bao giờ đưa tài liệu chưa chia sẻ hoặc đã bị thu hồi vào prompt ngữ cảnh.
- **Tắt AI khi làm bài đánh giá (Rule D6):**
  - Khi sinh viên đang trong thời gian làm Assessment chính thức của lớp, AI Tutor tích hợp phải bị vô hiệu hóa.
- **Lớp lưu trữ (Rule H5):**
  - Trong lớp `ARCHIVED`, chỉ cho phép xem lịch sử chat cũ, không cho gửi câu hỏi AI mới.
- **Bảo vệ quyền riêng tư (Rule E5, F3):**
  - Giảng viên và Admin **không mặc định có quyền đọc nội dung hội thoại chat riêng tư** của sinh viên.
  - Các log hệ thống tuyệt đối không in nội dung hội thoại nguyên văn ra logger console hay audit.

---

## 3. Tiêu chí nghiệm thu (Acceptance Criteria & QAS-06)
- [ ] Chạy bộ kiểm thử QAS-06 (tối thiểu 100 câu hỏi test):
  - Độ chính xác trích dẫn $\ge$ 90%.
  - Mức độ bám sát nguồn (groundedness) $\ge$ 90%.
  - Tỷ lệ từ chối trả lời đúng khi thiếu chứng cứ $\ge$ 90%.
  - 0% rò rỉ dữ liệu xuyên lớp (không trích dẫn tài liệu của Lớp B khi đang hỏi ở Lớp A).
- [ ] Thử nghiệm thu hồi quyền tài liệu: Thu hồi tài liệu X ở Document Service $\to$ Ngay lập tức AI Tutor không còn dùng tài liệu X để trả lời ở câu hỏi tiếp theo (Rule B7).
- [ ] Thử nghiệm trong lớp `ARCHIVED`: Gửi tin nhắn mới bị từ chối với thông báo lớp đã lưu trữ.
- [ ] Cô lập lỗi (QAS-01, QAS-02): Khi tiến trình AI bị tắt hoặc LLM API lỗi, các chức năng khác của hệ thống (xem tài liệu, nộp bài) vẫn hoạt động bình thường.
