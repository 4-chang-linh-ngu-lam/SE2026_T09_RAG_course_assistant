# LUMI — BỘ HỒ SƠ YÊU CẦU VÀ THIẾT KẾ HỆ THỐNG

| Thuộc tính | Giá trị |
|---|---|
| Mã hồ sơ | LUMI-DOSSIER-001 |
| Phiên bản | **2.1 – DỰ THẢO · bổ sung hồ sơ kiến trúc và môi trường thực nghiệm** |
| Ngày lập | 31/10/2026 |
| Repository | `4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant` |
| Mốc thiết kế gốc | `main` — commit `55324dc37c85c111d439a22f57f5e26544de9ce6` (cơ sở kiểm kê ban đầu) |
| Đối chiếu cập nhật | `main` — commit `382ceea5e0f474cacc2d22c8ab03b99c4c13bd0c` (tài liệu và triển khai ngày 31/10/2026) |
| Trạng thái | **Dự thảo thiết kế, chưa được phê duyệt; không phải bằng chứng triển khai** |
| Phạm vi | Core, Web, Document, Learning, Learner Intelligence; **không đặc tả AI Service** |
| Ngôn ngữ | Tiếng Việt trang trọng, thống nhất; chỉ giữ thuật ngữ kỹ thuật và tên chuẩn khi cần |

> **Ghi nhận mới khi hợp nhất:** Theo cập nhật trên `main` ngày 31/10/2026, mẫu thư mời và khôi phục tài khoản nhân sự đã được triển khai lên Cloud Run Production mock từ commit `a01985e`. API và tác vụ xử lý nền đã nhận cấu hình `PUBLIC_WEB_URL` trỏ đến Vercel Production; **chưa xác minh nội dung một thư thực nhận mới sau triển khai**. Các sơ đồ và phần thiết kế bên dưới giữ nguyên mốc nghiên cứu gốc, không phải xác nhận môi trường thực tế đã được kiểm thử lại.

## 1. Mục đích và cách sử dụng

Đây là **bộ tài liệu có cấu trúc và truy vết**, xây dựng dựa trên tài liệu hiện hành của Lumi và ba tài liệu mẫu do chủ dự án cung cấp. Bộ hồ sơ phục vụ bốn đối tượng: người quyết định nghiệp vụ, kiến trúc sư/lập trình viên, kiểm thử viên và người vận hành. Các tài liệu có vai trò khác nhau: yêu cầu diễn đạt *cái gì và vì sao*, thiết kế diễn đạt *làm như thế nào*, kiểm thử xác minh *đã đáp ứng hay chưa*.

**Thứ tự ưu tiên của các nguồn khi có khác biệt:** `docs/architect/BUSINESS_RULES.md` → ADR và kiến trúc đã duyệt → Core API Contract/OpenAPI/migration cho trạng thái triển khai → test/CI theo đúng commit → bộ tài liệu này. Nếu phát hiện xung đột, lập CR/open question, không sửa Business Rules để khớp bản nháp.

## 2. Danh mục tài liệu

| Mã | Tệp | Trả lời câu hỏi |
|---|---|---|
| BRD | [01_BRD.md](01_BRD.md) | Bài toán nghiệp vụ, mục tiêu, phạm vi, stakeholder, rủi ro là gì? |
| SRS | [02_SRS.md](02_SRS.md) | Hệ thống phải đáp ứng những yêu cầu có thể kiểm chứng nào? |
| FRS-CORE | [03_FRS_Core.md](03_FRS_Core.md) | Luồng chức năng Core chi tiết, validation, trạng thái lỗi thế nào? |
| FRS-DOC | [04_FRS_Document.md](04_FRS_Document.md) | Thư viện, chia sẻ, version, ghi chú vận hành thế nào? |
| FRS-LEA | [05_FRS_Learning.md](05_FRS_Learning.md) | Practice, Assessment, Assignment, grading và phúc khảo thế nào? |
| FRS-LI | [06_FRS_Intelligence.md](06_FRS_Intelligence.md) | Bằng chứng học tập, gợi ý, báo cáo và quyền riêng tư thế nào? |
| UC | [07_UseCases.md](07_UseCases.md) | Người dùng tương tác ra sao trong luồng chính và ngoại lệ? |
| HLD | [08_HLD.md](08_HLD.md) | Kiến trúc logic, deployment, service ownership và failure boundaries? |
| LLD-CORE | [09_LLD_Core.md](09_LLD_Core.md) | Thiết kế lớp/module, dữ liệu, transaction và cơ chế Core? |
| LLD-FUT | [10_LLD_Future.md](10_LLD_Future.md) | Phác thảo thiết kế Document, Learning, Intelligence — còn chờ duyệt? |
| MODEL | [11_ERD_DFD.md](11_ERD_DFD.md) | ERD, DFD, luồng sự kiện và ranh giới dữ liệu? |
| API | [12_API_Contracts.md](12_API_Contracts.md) | HTTP, quyền, lỗi, version, API hiện có và hợp đồng đề xuất? |
| UI | [13_UIUX.md](13_UIUX.md) | Vai trò, màn hình, trường/nút, tương tác và trạng thái? |
| SEC | [14_Security_Privacy.md](14_Security_Privacy.md) | Rủi ro bảo mật, privacy, audit và data requests? |
| OPS | [15_Operations.md](15_Operations.md) | Môi trường, migration, triển khai, giám sát và phục hồi? |
| TP | [16_Test_Plan.md](16_Test_Plan.md) | Chiến lược kiểm thử, môi trường, entry/exit criteria? |
| TC | [17_Test_Cases.md](17_Test_Cases.md) | Test case từng bước với expected result? |
| RTM | [18_Traceability.md](18_Traceability.md) | Rule → FR/NFR → thiết kế → test được nối ra sao? |
| GOV | [19_Decisions_Gaps.md](19_Decisions_Gaps.md) | Những giả định, quyết định chưa duyệt, thay đổi và blocker? |
| GLO | [20_Glossary_References.md](20_Glossary_References.md) | Thuật ngữ, quy ước, nguồn tham khảo? |
| ARC-ATLAS | [21_ARCHITECTURE_ATLAS.md](21_ARCHITECTURE_ATLAS.md) | 16 sơ đồ kiến trúc đa góc nhìn: context, tầng, component, runtime, data, workflows? |
| DEP | [22_ENVIRONMENTS_DEPLOYMENT.md](22_ENVIRONMENTS_DEPLOYMENT.md) | Các môi trường local, CI, staging, cloud mock, topology/network/ports và sizing? |
| EXP | [23_EXPERIMENTAL_ENVIRONMENT.md](23_EXPERIMENTAL_ENVIRONMENT.md) | Môi trường thực nghiệm, dataset, benchmark, fault injection và reproducibility? |
| ARC-QA | [24_ARCHITECTURE_SECURITY_OPERATIONS.md](24_ARCHITECTURE_SECURITY_OPERATIONS.md) | Threat model, trust, đánh đổi, SLO, release, DR/incident và ADR? |
| REF | [25_REFERENCE_AND_GAP_REVIEW.md](25_REFERENCE_AND_GAP_REVIEW.md) | Đối chiếu các mẫu tài liệu công khai của CMC/FPT/Rikkeisoft và cơ quan Việt Nam; gap v1? |
| FIG | [26_DIAGRAM_CATALOG_AND_REVIEW.md](26_DIAGRAM_CATALOG_AND_REVIEW.md) | Danh mục 16 sơ đồ, tệp chỉnh sửa và quy trình kiểm soát thay đổi |
| STYLE | [27_CONVENTIONS_AND_VIETNAMESE_STYLE.md](27_CONVENTIONS_AND_VIETNAMESE_STYLE.md) | Quy chuẩn viết tiếng Việt, thuật ngữ và hình thức trình bày |

## 3. Các trạng thái dùng xuyên suốt

| Ký hiệu | Ý nghĩa | Cách dùng |
|---|---|---|
| **DECIDED** | Nghiệp vụ đã quyết định | Có mã Rule trong Business Rules |
| **IMPLEMENTED** | Có mã thực tế | Phải đối chiếu commit và đường dẫn code |
| **VERIFIED** | Có bằng chứng kiểm thử | Chỉ đúng phạm vi/môi trường được ghi |
| **PROPOSED** | Thiết kế để xem xét | Không được tự coi là API/schema đã phê duyệt |
| **PENDING** | Cần chốt hoặc chưa làm | Ghi rõ owner/quyết định cần thiết |
| **DEFERRED** | Hoãn theo phạm vi | Không quảng bá như đã chạy |
| **OUT OF SCOPE** | Không có trong đợt tài liệu này | Không viết LLD, API, test tương ứng |

## 4. Phạm vi release: phân biệt hai khái niệm MVP

- **Sản phẩm thử nghiệm phần lõi (Core MVP 0.1):** Identity, Administration, Classroom, Social, Calendar, Notification và Web dùng API thật. Các luồng Core vẫn cần xác minh browser E2E theo hồ sơ hiện hành.
- **Phiên bản sản phẩm Lumi đầy đủ theo định hướng nghiệp vụ:** bao gồm Document, Learning, Learner Intelligence và một số năng lực AI trong Business Rules gốc. **Trong bộ hồ sơ hiện tại chỉ đặc tả Document/Learning/Intelligence dưới dạng PROPOSED**, không coi chúng đã có phía máy chủ.
- **Dịch vụ trí tuệ nhân tạo:** chưa thuộc phạm vi đặc tả yêu cầu, thiết kế chi tiết, API hoặc kiểm thử theo yêu cầu của chủ dự án. HLD chỉ ghi một placeholder tương lai, không đưa ra kiến trúc hay giải pháp kỹ thuật.

Không nên dùng chữ “MVP hoàn thành” nếu chỉ có Core/Web mà chưa đáp ứng sản phẩm đầy đủ như Business Rules.

## 5. Quy tắc triển khai từ bộ hồ sơ

1. Khi chuẩn bị code, chọn một FR-ID và ít nhất một Use Case/Test Case liên quan; xác nhận trạng thái API/schema tại HEAD.
2. Với `PROPOSED`, cần chủ dự án phê duyệt thiết kế trước khi triển khai chi tiết, nhất là dữ liệu học sinh, điểm và retention.
3. Với yêu cầu cắt ngang service, phải quyết định nguồn dữ liệu có thẩm quyền, nguyên tắc phân quyền hiện hành, khả năng retry, idempotency và quan sát lỗi.
4. Mọi thay đổi có tác động đến Business Rules cần CR và traceability cập nhật; không sửa bản chuẩn bằng suy đoán.
5. Lưu bằng chứng test theo đúng source commit và môi trường; ảnh chụp UI mock không chứng minh phía máy chủ production.

## 6. Lịch sử phiên bản

| Phiên bản | Ngày | Tác động | Duyệt |
|---|---|---|---|
| 1.0-DRAFT | 31/10/2026 | Khởi tạo bộ BRD/SRS/FRS/HLD/LLD/UC/ERD/DFD/UI/Test/RTM, loại AI khỏi thiết kế chi tiết | Chưa |

> Tài liệu này là sản phẩm biên soạn mới để review, là bộ hồ sơ mới đưa vào GitHub; bản tổng hợp 0.1 được lưu trong lịch sử Git, còn Business Rules và hợp đồng hiện hành tiếp tục là nguồn chuẩn.


## 7. Nội dung nâng cấp phiên bản 2.1 (31/10/2026)

- Không xóa nội dung v1: giữ BRD/SRS/FRS/LLD/Use Case/Test/RTM làm baseline, bổ sung 6 tập kiến trúc chuyên sâu.
- Có 16 sơ đồ Mermaid `.mmd` trong `diagrams_arch/`, phân biệt hiện trạng, thiết kế logic, môi trường cloud báo cáo và đề xuất.
- Đối chiếu thêm các tài liệu công khai của CMC Global, FPT Software, Rikkeisoft và hồ sơ thiết kế kỹ thuật công khai tại Việt Nam; nội dung nghiệp vụ Lumi vẫn do Business Rules/ADRs/code làm nguồn chuẩn.
- Không đặc tả AI Service. Các giá trị môi trường chưa được xác minh, số đo chưa chạy, service chưa triển khai vẫn được đánh dấu rõ.

| Phiên bản | Ngày | Tác động | Duyệt |
|---|---|---|---|
| 2.0-DRAFT | 31/10/2026 | Bộ sơ đồ kiến trúc; mạng và triển khai; môi trường thực nghiệm; an toàn, phát hành và khôi phục sự cố; 16 sơ đồ | Chưa |