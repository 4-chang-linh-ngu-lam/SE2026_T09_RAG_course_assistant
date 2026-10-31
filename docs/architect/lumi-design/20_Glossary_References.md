# THUẬT NGỮ, VIẾT TẮT VÀ TÀI LIỆU THAM KHẢO

**Mã:** LUMI-REF-001 · **Phiên bản:** 1.0-DRAFT.

## 1. Thuật ngữ

| Thuật ngữ | Ý nghĩa trong Lumi |
|---|---|
| BRD | Business Requirements Document — Yêu cầu nghiệp vụ, mục tiêu, scope, stakeholder |
| SRS | Software Requirements Specification — Đặc tả yêu cầu phần mềm có thể kiểm chứng |
| FRS | Functional Requirements Specification — Đặc tả logic chức năng, form, validation, error |
| HLD | High-Level Design — Thiết kế kiến trúc vĩ mô và các góc nhìn |
| LLD | Low-Level Design — Thiết kế module, dữ liệu, state/transaction và API |
| UC | Use Case — Kịch bản actor/hệ thống và các ngoại lệ |
| ERD | Entity-Relationship Diagram — Sơ đồ thực thể và quan hệ |
| DFD | Data Flow Diagram — Sơ đồ luồng dữ liệu |
| RTM | Requirements Traceability Matrix — Ma trận truy vết yêu cầu/test/code |
| ADR | Architecture Decision Record — Hồ sơ quyết định kiến trúc |
| API | Application Programming Interface — Hợp đồng giao tiếp giữa các thành phần |
| RBAC | Role-Based Access Control — Quyền theo vai trò; Lumi còn có action/class/school scope |
| School scope | Giới hạn dữ liệu và quyền trong một trường |
| Homeroom | Lớp hành chính, có roster gắn năm học/khối |
| Subject class | Lớp môn học, có course/year/semester/teachers/membership |
| PRIMARY | Giáo viên chính được Admin phân công, có quyền phê duyệt nhạy cảm |
| ASSISTING | Giáo viên phối hợp, có quyền theo assignment hiện hành |
| AUTO enrollment | Ghi danh tự động theo roster homeroom |
| MANUAL enrollment | Admin điều chỉnh membership theo danh sách riêng |
| Membership episode | Một đợt ghi danh với joined_at/ended_at và lịch sử |
| School mapping | Gán School hợp lệ cho tài khoản legacy theo nguồn thẩm quyền |
| Token rotation | Thu hồi refresh cũ và cấp refresh mới |
| Outbox | Bảng ghi event cùng transaction nghiệp vụ để worker tiêu thụ |
| Recipient snapshot | Danh sách người nhận được chốt tại thời điểm sự kiện được tạo |
| Idempotency | Replay cùng thao tác không tạo tác dụng nghiệp vụ lặp không mong muốn |
| Optimistic concurrency | Gửi expected version/revision và từ chối cập nhật stale |
| Fail closed | Không xác nhận được quyền thì không cung cấp tài nguyên nhạy cảm |
| Provenance | Nguồn, version, thời điểm và điều kiện sinh ra evidence |
| Mastery | Mức độ nắm vững chủ đề; không kết luận khi thiếu bằng chứng |
| Complementary suppression | Ẩn thêm ô/bảng phụ để không suy ra ô nhạy cảm đã bị ẩn |
| RPO/RTO | Mục tiêu điểm phục hồi/mục tiêu thời gian phục hồi, hiện chưa chốt production |
| TP-01 | Cấu hình thử nghiệm tải được nêu trong Quality Attributes |
| Core MVP 0.1 | Bản chạy Core + Web live; không đồng nhất Product MVP đầy đủ |
| PROPOSED | Thiết kế chờ review, chưa phải implementation/contract approved |
| IMPLEMENTED | Có code trong revision được ghi |
| VERIFIED | Có evidence đã chạy trên revision/môi trường được ghi |

## 2. Nguồn nội bộ Lumi — ưu tiên theo vai trò

| Thứ tự | Đường dẫn repository | Dùng để |
|---:|---|---|
| 1 | `docs/architect/BUSINESS_RULES.md` | Rule ID nghiệp vụ A–O, quyết định đã chốt |
| 2 | `docs/architect/microservices-v1/ADR-001.md` | Monorepo/microservices/ownership |
| 3 | `docs/architect/microservices-v1/ARCHITECTURE.md` | Service boundaries và logical architecture |
| 4 | `docs/architect/SYSTEM_DESIGN.md` | SDD tổng hợp v0.1 tại 31/10/2026 |
| 5 | `docs/architect/microservices-v1/core/DESIGN.md` | Core implementation/design notes |
| 6 | `docs/architect/microservices-v1/core/API_CONTRACT.md` | Core endpoint/permission/error contract |
| 7 | `docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md` | QAS-01..11 và TP-01 |
| 8 | `docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md` | G0–G5 và acceptance gates |
| 9 | `services/core/app/modules/**/models.py` và Alembic | Physical data truth tại revision |
| 10 | `services/core/app/modules/**/router.py` và OpenAPI | HTTP implementation truth |
| 11 | `services/core/README.md`, `services/core/migrations/README.md` | Runtime/seed/migration |
| 12 | `apps/web/README.md`, `apps/web/src/lib/data/integrations.ts`, `apps/web/FRONTEND_COMPLETION.md` | Web routes, data mode, live vs mock limitations |
| 13 | `tasks/README.md`, `tasks/TASK-001`…`TASK-020` | Task-level scope/evidence, một số snapshot lịch sử |

**Repository URL:** https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant

**Mốc đối chiếu:** `55324dc37c85c111d439a22f57f5e26544de9ce6` (31/10/2026). Thông tin CI/runtime có thể thay đổi; không suy ra trạng thái ngoài revision này.

## 3. Ba tài liệu mẫu do người dùng cung cấp

1. **NASA — Information Management Platform for Data Analytics and Aggregation (IMPALA), System Design Document**, August 2016; file `20160011412.pdf` (71 trang). Bố cục tham khảo: kiểm soát tài liệu, tổng quan, architecture views, security/data governance, operational scenarios, detailed design, interfaces.
2. **U.S. Government Printing Office — Federal Digital System, System Design Document Volume I: System Architecture**, R1C2, September 2008; file `FDsys_Architecture.pdf` (87 trang). Tham khảo cấu trúc nhiều volume, system overview, lifecycle, architecture viewpoints, external interfaces/deployment.
3. **Mẫu Tài liệu Thiết kế Hệ thống Dự án — Phiên bản 1.0**, file `[studocu.com] - Mẫu Tài Liệu Thiết Kế Hệ Thống Dự Án - Phiên Bản 1.0.pdf` (16 trang). Tham khảo khuôn trình bày tổng quan, CSDL, UI, class/flow, kiểm soát truy cập/giao dịch/nhật ký/backup.

Các mẫu được dùng **để tham khảo cách tổ chức hồ sơ**; không sao chép kiến trúc, yêu cầu, thông số của NASA/FDsys hoặc ví dụ thư viện/PHP vào Lumi.

## 4. Những gì bộ hồ sơ **không** xác nhận

- Không có khảo sát stakeholder độc lập, nghiên cứu pháp lý hoặc benchmark mới trong quá trình biên soạn.
- Không chạy lại CI/browser E2E ở commit 55324dc; mọi test case mới đều là NOT RUN.
- Không phê duyệt migration/API/algorithm/storage của Document, Learning, Learner Intelligence.
- Không cung cấp SRS/LLD/Test Cases cho AI Service, theo yêu cầu loại khỏi phạm vi hiện tại.
- Không phê duyệt retention/identity verification/production DR hay KPI chưa có căn cứ.

## 5. Chất lượng của một bản cập nhật tài liệu

Mọi thay đổi bổ sung phải ghi rõ **source file/commit → câu thay đổi → trạng thái DECIDED/IMPLEMENTED/PROPOSED → ảnh hưởng FR/test → reviewer**. Đừng chỉ tăng số trang mà không làm rõ nguồn gốc và kiểm chứng.