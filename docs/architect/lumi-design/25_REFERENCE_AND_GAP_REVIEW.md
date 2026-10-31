# PHẦN E — THAM KHẢO TÀI LIỆU VIỆT NAM VÀ ĐÁNH GIÁ MỨC ĐỘ HOÀN THIỆN

**Mã:** LUMI-REF-002 · **Ngày đối chiếu:** 31/10/2026 · **Mục đích:** xác định chính xác các phần mà bộ hồ sơ Lumi 1.0 còn thiếu và lý do bổ sung.  
**Tuyên bố nguồn:** các tài liệu công khai dưới đây là **tư liệu tham khảo về phương pháp/hình thức**, không phải đặc tả nghiệp vụ hay tài liệu nội bộ chính thức của Lumi. Không suy luận một công ty áp dụng đúng mọi bước trong bài blog/slide của họ.

## E1. Kết quả nghiên cứu tài liệu thực tế ở Việt Nam

| Nguồn công khai | Thông tin có thể kiểm chứng | Bài học đưa vào Lumi | Giới hạn |
|---|---|---|---|
| **CMC Global – Sales Pitching Deck 2025** (tài liệu công khai trên domain công ty) | Có *Project Journey* `Scope → Discovery → Ideate → Design → Develop → Testing → Deploy`; giai đoạn Design ghi HLD/LLD; Testing có test case, kiểm tra, còn Deploy có sanity/user check | Phân biệt đầu ra thiết kế với evidence kiểm thử và release; thêm CI/E2E/release gates | Deck giới thiệu doanh nghiệp, **không phải** template kỹ thuật bảo mật/LLD chi tiết của một dự án cụ thể |
| **FPT Software – tài liệu IVS Automation Testing 2025** (công khai trên domain doanh nghiệp) | Mô hình continuous testing có HLD, test case design, unit/integration/system/UAT, infrastructure baseline, rollout/verification logs | Lập chương thực nghiệm với traceability, runner, kết quả và giới hạn, không chỉ mô tả “đã test” | Slide về quy trình/quality, **không** cho phép sao chép kiến trúc sản phẩm nội bộ của FPT |
| **Rikkeisoft – Managed Service (public)** | Quy trình công khai gồm yêu cầu/phân tích, thiết kế kiến trúc/lộ trình, triển khai, QA và bảo trì/giám sát | Tách nhiệm vụ kiến trúc, bàn giao và vận hành; bổ sung monitoring và release/incident runbook | Nội dung ở mức dịch vụ công khai, không phải hồ sơ dự án khách hàng |
| **Bộ TN&MT – Quyển 2 thiết kế chi tiết hệ thống thu nhận/tích hợp/chia sẻ dữ liệu địa chất (2023)** | Có chương kiến trúc phần mềm, các quy trình tin học hóa, đối tượng dữ liệu, mô tả chức năng/UC và mô hình triển khai kèm yêu cầu hạ tầng | Thêm mô hình triển khai riêng, mô hình dữ liệu, bảng chức năng, ranh giới data và sơ đồ use case | Tài liệu cơ quan nhà nước, **không phải của công ty tư nhân**; cấu trúc tham khảo, không áp yêu cầu pháp lý dự án đầu tư công cho Lumi |
| **Tài liệu thiết kế thi công hạ tầng kỹ thuật/ATTT cho Tổng cục KTTV (2023)** | Mục thiết kế tổng thể có sơ đồ logic hạ tầng, phân vùng App/DB, an toàn, mô tả luồng dữ liệu, định cỡ, lắp đặt và triển khai | Phân biệt logical/network/deployment views, bảng tài nguyên, ranh giới tin cậy, phân vùng và sizing | Dự án trung tâm dữ liệu chuyên dụng; **không** mô phỏng firewall/Nexus/DR vật lý đó cho Lumi cloud |
| **3 PDF người dùng cung cấp**: NASA IMPALA, FDsys Architecture, mẫu thiết kế hệ thống tiếng Việt | IMPALA có logical/functional/infrastructure/network/security; FDsys chia volume; mẫu Việt có sơ đồ tổng thể, DB, UI, kiểm soát | Giữ các phần BRD/SRS/FRS/LLD hiện có nhưng tổ chức kiến trúc thành một tập atlas + triển khai + thực nghiệm riêng | Không sao chép giải pháp cụ thể hoặc nhận diện hệ thống khác là kiến trúc Lumi |

### E1.1. Liên kết tài liệu tham khảo công khai

- **[CMC Global – Quy trình phát triển phần mềm theo yêu cầu](https://cmcglobal.com.vn/vi/service/custom-software-development-4/)** — trình bày rõ các giai đoạn nhận diện yêu cầu, thiết kế, xây dựng, triển khai và bảo trì.
- **[MISA – Các bước trong quy trình phát triển phần mềm](https://amis.misa.vn/220037/quy-trinh-phat-trien-phan-mem/)** — phân biệt yêu cầu, kiến trúc, giao diện, cơ sở dữ liệu, kiểm thử và triển khai.
- **[CMC Global – Sales Pitching Deck 2025](https://cmcglobal.com.vn/wp-content/uploads/2025/07/Sales-Pitching-Deck-2025-ENG-230625.pdf)** — *Project Journey* và HLD/LLD.
- **[FPT Software – IVS Automation Testing 2025](https://fptsoftware.com/-/media/project/fpt-software/fso/pages/nha-trang-sfx/booth-3/1-ivs-automation-testing-2025-updated.pdf?modified=20250609040318)** — continuous testing và release quality gates.
- **[Rikkeisoft – Managed Service](https://dev.rikkeisoft.com/vi/managed-service/)** — quy trình từ discovery đến vận hành.
- **[Cục Chuyển đổi số/TN&MT – mẫu thiết kế chi tiết phần mềm](https://tailieuhoinghi.mae.gov.vn/Data/files/2023/CCNTT/5%20-%20Mau%20TKTC%20Phan%20mem_Final_K_230825.pdf)** — quyển 2, các mục kiến trúc, chức năng, dữ liệu và triển khai.
- **[Tài liệu thiết kế thi công hạ tầng kỹ thuật/ATTT – Tổng cục KTTV](https://tailieuhoinghi.mae.gov.vn/Data/files/2023/CCNTT/3_%20KTTV_ThietKeThiCong_V1_0_2023_08_24_Thang_updated.pdf)** — thiết kế logic, network, sizing/triển khai.
- **[Bộ VHTTDL – Bộ tài liệu Kiến trúc tổng thể số](https://kientruc.bvhttdl.gov.vn/)** — kiến trúc mục tiêu, kiến trúc dữ liệu, quản trị và từ điển dữ liệu. Website có lúc không truy cập được; xem đây là nguồn bối cảnh, không nguồn chi tiết bắt buộc.

**Không tuyên bố** đã tìm được/tải được tài liệu HLD/LLD nội bộ của CMC, FPT hay Rikkeisoft. Phần lớn hồ sơ khách hàng doanh nghiệp không được công bố; do đó những ví dụ nêu trên là công khai và chỉ chứng minh phương pháp trình bày.

## E2. Những điểm còn thiếu trong hồ sơ Lumi phiên bản trước

| Khoảng trống của bản 1.0 | Rủi ro khi review/bảo vệ | Nơi bổ sung trong v2 |
|---|---|---|
| Có context nhưng thiếu bản đồ kiến trúc **theo tầng** với giải thích tầng | Người đọc nhầm module, tier, service và host | A03; `21_ARCHITECTURE_ATLAS.md` A4 |
| Gộp logic và physical deployment | Không biết container nào chạy ở đâu | A04/A06/A07/A08; `22_ENVIRONMENTS_DEPLOYMENT.md` |
| Một sơ đồ tổng thể chứa cả service chưa triển khai | Nhầm “planned architecture” với “implemented architecture” | A01/A02/A15, nét liền/nét đứt |
| Thiếu môi trường thực nghiệm cụ thể và tính tái lập | Không thể đánh giá kết quả p95/coverage | `23_EXPERIMENTAL_ENVIRONMENT.md` |
| Ít diễn giải vùng mạng và ranh giới tin cậy | Sơ đồ chưa làm rõ đường truy cập và nơi enforce quyền | A09 và các bảng SEC-01–SEC-10 |
| Chưa tách environment local/CI/staging/mock/prod thực | Dễ áp sai seed, dữ liệu hoặc cấu hình secret | B2/B3/B4/B6 |
| Chưa phân biệt CI xanh với browser E2E và acceptance | Khẳng định “MVP hoàn tất” thiếu bằng chứng | C3–C9, D6 |
| Chưa có capacity sizing/giới hạn phép đo | Dễ gọi 100-user class-list benchmark là 358 CCU production | B7, C4 |
| Chưa có release provenance/rollout/drift | Runtime khác source repo, khó debug | A13, B4, D6 |
| Thiếu DR/incident thực tế, retention và privacy gate | Demo ổn nhưng chưa đủ vận hành học sinh thật | A16, D6, ADR backlog |
| Chưa có catalog sơ đồ để review | Mỗi lần thay kiến trúc phải vẽ lại thủ công | `diagrams_arch/` DOT + PNG + SVG |

## E3. Cấu trúc đề xuất cho bộ hồ sơ thiết kế Lumi

| Lớp tài liệu | Nội dung | Vai trò |
|---|---|---|
| 01 BRD/SRS/FRS | Nghiệp vụ, FR/NFR, màn hình, validation và user actions | WHAT/WHY |
| 02 Use Cases | Actor, luồng chính/phụ, pre/post, exception | WHAT/HOW ở mức nghiệp vụ |
| 03 Architecture Atlas | Context, capability, layered, container, component, data, trust, dynamic, deployment | HLD có nhiều viewpoint |
| 04 Core LLD | Model/tables, methods/public interfaces, transaction, states, idempotency | Thiết kế triển khai chi tiết |
| 05 Service Design đề xuất | Document, Learning, Intelligence | PROPOSED, cần approval |
| 06 Integration/API | OpenAPI, role matrix, error, event contract, dependencies | Giao diện liên hệ thống |
| 07 Network/Deployment | Local/CI/Cloud/target, ingress/egress, ports, secrets, migrations | Vận hành và topology |
| 08 Experimental Environment | Môi trường thực nghiệm, dataset, metrics, scripts, results, limits | Tính tái lập học thuật |
| 09 Security & Data Governance | RBAC+context, threat model, privacy, retention, audit | Rủi ro kiểm soát |
| 10 Test Plan/Case & RTM | Functional/negative/concurrency/performance/recovery, traceability | Verification |
| 11 ADR/Release/Operations | Tech tradeoffs, incident/backup/DR, change control và go/no-go | Maintenance/Acceptance |

Không phải tất cả mục cần nằm trong **một file Word**. Để công cụ lập trình và reviewers tìm nhanh, nên giữ Markdown phân file và có một quyển tổng hợp (generated PDF/DOCX) phục vụ nộp.

## E4. Kiểm tra chất lượng hồ sơ thiết kế (không đánh giá chất lượng sản phẩm)

| Tiêu chí | Cách kiểm chứng | Kết quả phiên bản v2 |
|---|---|---|
| Có ít nhất 3 viewpoint kiến trúc độc lập | Context/Layered/Deployment có hình và chú giải | Có A01/A03/A06–A08 |
| Mọi sơ đồ ghi current/target | Chú thích rõ IMPLEMENTED/PROPOSED và đường nét | Có ở chapter/diagram catalog |
| Có tài liệu môi trường thực nghiệm | CPU/RAM/versions/mô hình tải/evidence form | Có; giá trị chưa đo ghi TBD |
| Triển khai local bám cấu hình repo | Có service/port/health/startup order | Đối chiếu `compose.yaml` |
| CI bám quy trình xử lý thật | Có job, runner, PG version và artifact | Đối chiếu `core-ci.yml` |
| Cloud chỉ báo cáo phần thực có evidence | Không tự vẽ autoscaling/WAF/Redis | Đã gắn REPORTED/TBD |
| Kế hoạch test không bị gọi là kết quả | Phân loại target/measured/missing | Có C1–C9 |
| AI Service không được thiết kế kỹ thuật | Không có API/schema/model/vector pipeline | Giữ future placeholder |
| Tài liệu có thể chỉnh sửa | Mermaid/DOT/Markdown và PDF/DOCX bổ trợ | DOT/PNG/SVG + Markdown |

## E5. Quy trình thẩm định trước khi đưa vào nhánh chính

1. Kiểm tra Git HEAD mới nhất và thay đổi sau baseline `55324dc`; nếu có commit mới, chạy diff đối chiếu environment/CI/API/migrations và cập nhật những chỗ bị ảnh hưởng.
2. Architect xác nhận các sơ đồ A01–A16 không mô tả service chưa có là đã triển khai.
3. DevOps xác minh Cloud Run/Vercel/Neon revision, worker, `PUBLIC_WEB_URL`, secret rotation, image digest, DB head; bổ sung bằng chứng mới nếu cần.
4. BA xác nhận Business Rules; không sửa quyền Admin/Lecturer/Student để khớp sơ đồ.
5. QA xác nhận môi trường thực nghiệm và metrics có thể thực sự chạy lại, không đưa số 358 CCU/TP-01 vào mục achieved khi chưa đo.
6. Policy/Operator quyết định retention/DELETE, DR/backup và production go/no-go, không yêu cầu agent tự phê duyệt.
7. Chỉ sau review mới nâng tài liệu từ `DRAFT` lên `APPROVED`, kèm version/changelog/commit evidence.