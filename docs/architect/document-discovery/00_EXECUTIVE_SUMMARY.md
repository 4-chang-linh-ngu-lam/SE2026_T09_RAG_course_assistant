# DOC-00 — Tổng kết khảo sát kỹ thuật Document Service

- **Trạng thái:** DOC-00 — DISCOVERY APPROVED, CLOSED.
- **Ngày khảo sát:** 25/11/2026
- **Phạm vi:** đối chiếu mã nguồn hiện tại với DOC-D01–07, DOC-T01–07 đã được chấp thuận; chỉ khảo sát các điểm RAG cần để tích hợp. Không khảo sát lại thuật toán AI/RAG.

## Approval boundary

Technical Lead đã phê duyệt DOC-00 và DOC-00-R1 ở cấp Discovery. Implementation chưa được nghiệm thu; toàn bộ 48 DOC-T06 Acceptance Criteria chưa VERIFIED. Các blocker/open decisions trong tài liệu 09 vẫn có hiệu lực. DOC-01 chưa được phép bắt đầu.

## 1. Git safety và baseline

| Tham chiếu | Giá trị |
|---|---|
| Repository | 4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant |
| Nhánh local được khảo sát | codex/rag-technical-discovery |
| HEAD sau pull --ff-only | c7f56c722f421bf1df17f5a82f26a78682eb82be |
| HEAD trước pull | 2d975514c4d017fe135b38df13652714b33433eb |
| origin/main | dc0671c36bf750ef914ac34d22e6ff2cf685287a |
| origin/codex/rag-technical-discovery | c7f56c722f421bf1df17f5a82f26a78682eb82be |

Trước pull, local ở 2d97551 với các mục chưa track docs/architect/document-discovery/, docs/problem/ và stitch-rag-consistency.zip. HEAD là ancestor của remote; pull --ff-only fast-forward tới c7f56c7, thêm 38 file / 667 dòng, toàn bộ là tài liệu. Các file DOC-00 và dữ liệu local được giữ nguyên; không có thay đổi application code.

Trên baseline mới nhất, DOC-D01–07/DOC-T01–07, CORE-D01–08/CORE-T01–08, LRN-D01–10/LRN-T01–10, NTF-D01–05/NTF-T01–05 và SYS-D01–05/SYS-T01–07 được ghi ACCEPTED ở mức thiết kế. RAG-D02 vẫn DEFERRED. Quyết định thiết kế không xác nhận implementation/acceptance.

## 2. Kết luận

**Document Service backend chưa được triển khai và chưa thể tích hợp frontend hoặc RAG theo hợp đồng đã duyệt.** Repository hiện có Core và thư viện RAG offline; không có thư mục/service Document, database/migration, API, storage nguồn, grant/version lifecycle, AI HTTP adapter hay Document worker.

Web đã có màn hình và mô hình dữ liệu phía giao diện cho tài liệu. Ở live mode, các thao tác Document đều trả 503; API allowlist chỉ nhận Core operations. Do đó màn hình/mocks không phải bằng chứng rằng nghiệp vụ Document đang hoạt động trên backend.

| Khả năng | Hiện trạng | Phân loại chính |
|---|---|---|
| Core identity/classroom và quyền lớp | Có FastAPI, PostgreSQL/Alembic và internal check-class-access; chưa có API Document grants | EXISTS_NEEDS_CHANGE |
| Document Service / 4 bảng DOC-T02 | Không tìm thấy implementation hoặc migration | MISSING |
| File gốc, version, grant, deletion lifecycle | Chưa có service quản lý nguồn | MISSING |
| RAG pipeline | Python library/CLI, xử lý và truy hồi offline; không có HTTP API | EXISTS_NEEDS_CHANGE |
| Durable Document→AI REST jobs | Chưa có; worker RAG hiện tại dùng file cục bộ | MISSING |
| Web live Document API | Adapter trả UNAVAILABLE/503; document integration là pending-contract | MISSING |
| Kiểm thử tích hợp 48 AC | Chưa có test Document–AI–Core end-to-end | MISSING |

## 3. Ưu tiên và rủi ro lớn

1. Xây Document Service sở hữu file/version/grant/job trong database riêng; không thêm bảng Document vào Core schema và không tạo FK/SQL xuyên service.
2. Service JWT là foundation dùng chung SYS-02/CORE-T04; Document chỉ tích hợp verifier/client, không tự tạo issuer, key store hoặc auth riêng. Code Core hiện còn X-Service-Key nên implementation foundation chưa được xác minh.
3. Chốt contract giữa Document và nhóm AI: durable submit/status/delete, tải file theo version và job, readiness/index reference, scope validate. Không thay đổi pipeline nội bộ RAG trong DOC-00.
4. RAG chỉ là engine offline: input mặc định cho phép tới 512 MiB, nhiều loại tệp hơn danh sách FRS Document; giới hạn upload/MIME/quarantine của sản phẩm còn phải được chốt. Không truyền metadata ACL của RAG làm bằng chứng quyền.
5. Chính sách retention/xóa và dọn index/file chưa đủ căn cứ triển khai xóa vĩnh viễn; phải giữ fail-safe và chặn truy vấn ngay khi quyền bị thu hồi.

## 4. Bằng chứng kiểm thử và giới hạn

- Workflow Core CI có job RAG tests, Core/PostgreSQL tests, Web build và Docker Compose smoke; job load là tùy chọn thủ công.
- Tài liệu khảo sát RAG trước đó ghi CI PR #49: 144 passed, 2 skipped, 1 xfailed, 2 warnings. Đây là evidence được ghi lại trong báo cáo trước, không phải run vừa thực hiện hoặc nghiệm thu Document.
- Git tree tại 680beaf, 2d97551, dc0671c và c7f56c7 đều có 15 file test_*.py trong services/rag; không có thay đổi test tree trong 2d97551..c7f56c7. Con số 21 ở báo cáo cũ không tái lập được từ các refs này; nguồn/scope chưa xác minh.
- Không chạy pytest, npm, Docker hoặc test ngoài workspace trong lượt này: Python hệ thống là 3.11.9, pytest chưa cài, RAM trống quan sát được khoảng 1.21 GB. Không cài dependency hoặc tải model.

## 5. Roadmap đề xuất

Backlog đã căn theo Master Implementation Plan: Phase 0 discovery/contracts; Phase 1 SYS-01–03 và CORE-01–04; Phase 2 DOC-01–08 song song với Learning/Notification sau foundation; Phase 3 DOC-09–13 AI integration; Phase 4 frontend; Phase 5 E2E/security/load/restore/final acceptance. DOC-03 chỉ tích hợp JWT foundation. Roadmap vẫn chờ Technical Lead phê duyệt.

## 6. Deliverables

- [01 — Repository inventory](01_REPOSITORY_INVENTORY.md)
- [02 — Hiện trạng implementation](02_CURRENT_IMPLEMENTATION.md)
- [03 — Gap analysis](03_GAP_ANALYSIS.md)
- [04 — Tương thích API](04_API_COMPATIBILITY.md)
- [05 — Database và storage](05_DATABASE_AND_STORAGE_REVIEW.md)
- [06 — Security và resilience](06_SECURITY_AND_RESILIENCE_REVIEW.md)
- [07 — Coverage kiểm thử](07_TEST_COVERAGE_MATRIX.md)
- [08 — Backlog điều chỉnh](08_REVISED_IMPLEMENTATION_BACKLOG.md)
- [09 — Blockers và quyết định mở](09_BLOCKERS_AND_OPEN_DECISIONS.md)

**Kết thúc:** DOC-00 — DISCOVERY APPROVED, CLOSED.
