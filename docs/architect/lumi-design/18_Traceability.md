# RTM — MA TRẬN TRUY VẾT YÊU CẦU ↔ THIẾT KẾ ↔ KIỂM THỬ

**Mã:** LUMI-RTM-001 · **Trạng thái:** Thiết kế/kiểm thử liên kết trên giấy; kết quả test = NOT RUN trừ khi evidence runtime riêng được đính kèm.

## 1. Nguyên tắc

- Business Rule/FR-ID là trung tâm truy vết; không đánh dấu acceptance chỉ vì có thiết kế hoặc test case.
- Mỗi dòng phân biệt **Nguồn (Business Rule/QAS)**, **Bản thiết kế**, **Test case dự kiến**, **Trạng thái service** và **Bằng chứng kết quả**.
- Các requirement AI được loại khỏi SRS/RTM kỹ thuật. Business Rules gốc vẫn giữ các mã C1–C6, D6 và ràng buộc liên quan; bộ này không thiết kế chúng.
- Khi tạo PR, điền code file/commit và evidence tương ứng rồi đánh giá acceptance; các ô chưa rõ phải giữ PENDING.

## 2. Ma trận chức năng

| ID | Yêu cầu (rút gọn) | Rule/QAS | Thiết kế và trạng thái | Test (chưa chạy) |
|---|---|---|---|---|
| `FR-ID-01` | Student chỉ được tạo bởi Admin, có username duy nhất, không yêu cầu email; không cho … | F1 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-005`, `TC-006` |
| `FR-ID-02` | Student PENDING kích hoạt bằng code một lần có hạn, đặt mật khẩu; code sai/hết hạn/re… | F1 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-004` |
| `FR-ID-03` | Staff đăng nhập email, Student username; login trả access token và HttpOnly refresh c… | F1,K2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-001`, `TC-002`, `TC-028` |
| `FR-ID-04` | Hỗ trợ login, refresh rotation, logout, logout-all, password reset theo đúng loại tài… | F1 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-003` |
| `FR-ID-05` | Admin cùng trường tìm/lọc danh sách tài khoản, đổi role/status, ghi audit và thu hồi … | F1,F7 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-006`, `TC-007`, `TC-008` |
| `FR-ID-06` | Import CSV/XLSX phải preview lỗi/trùng, confirm, chống double-submit và không tạo trù… | F1,F2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-009`, `TC-010` |
| `FR-ID-07` | Admin duyệt được data requests theo trạng thái; không báo COMPLETED nếu chưa có polic… | F4,K1,K4,O8 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-025`, `TC-026` |
| `FR-ID-08` | Quyền nhạy cảm chỉ được cấp khi user còn ACTIVE, role/school hiện hành hợp lệ | F1,K2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-005` |
| `FR-CL-01` | Chỉ Admin tạo course/homeroom/subject class; lớp gắn môn, khối, năm học/học kỳ, mode … | A3,A7,A8 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-011`, `TC-013`, `TC-014`, `TC-030` |
| `FR-CL-02` | AUTO đồng bộ theo roster hành chính; MANUAL do Admin chỉ định; không có Student self-… | A1,A5,A6 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-013`, `TC-015` |
| `FR-CL-03` | Cho xem trước thay đổi và kiểm tra version trước sync/mode switch; stale phải trả con… | A1,F2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-011`, `TC-012`, `TC-015` |
| `FR-CL-04` | Admin thêm/kết thúc/chuyển membership, giữ lịch sử episode; bảo toàn kết quả cá nhân … | A4,L2,M1 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-016` |
| `FR-CL-05` | Admin phân công PRIMARY/ASSISTING, không để trống PRIMARY khi cần thay; teacher không… | A3,H1,H2,M2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-018` |
| `FR-CL-06` | Chỉ Admin archive/restore, ngừng hoạt động mới khi archived, kiểm tra lại quyền hiện … | F5,M5 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-017`, `TC-018` |
| `FR-CL-07` | Member/Teacher/Admin chỉ đọc tài nguyên theo trường, lớp, trạng thái, action hợp lệ; … | A4,L2 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-014`, `TC-016`, `TC-019` |
| `FR-SO-01` | Thành viên hiện hành xem/đăng feed theo quyền; sửa bài của mình; xóa mềm và ẩn nội du… | G1,L1 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-020`, `TC-030` |
| `FR-SO-02` | Bình luận trên post còn hiển thị; author sửa; moderation hợp lệ ẩn/xóa với audit | G2,L1,L5 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-021` |
| `FR-SO-03` | Giáo viên được phân công tạo/sửa/xóa Core calendar event; Student đọc trong lớp | G3 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-022` |
| `FR-SO-04` | Không cho đăng/sửa hoạt động chung mới trong lớp archived | F5,M5 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-017` |
| `FR-NO-01` | Người dùng xem inbox của chính mình, mark-read/read-all; không xem notification người… | G4,K5 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-024`, `TC-030` |
| `FR-NO-02` | Notification phát tới audience đúng thời điểm sự kiện; dedup/retry không gửi nhầm ngư… | F7,L3 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-023` |
| `FR-NO-03` | Payload notification không chứa password, token, nội dung chat riêng tư, tài liệu ngu… | F3,K5 | 03_FRS_Core.md, 09_LLD_Core.md — CORE BACKEND / E2E PENDING | `TC-031` |
| `FR-DOC-01` | Lecturer có thư viện cá nhân và sở hữu nguồn; một nguồn chia sẻ nhiều lớp | B1,B2 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T01`, `DOC-T02` |
| `FR-DOC-02` | Hỗ trợ PDF/PPTX/DOCX/TXT/Markdown với xử lý/validation và thông tin lỗi | B3,B5 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T03`, `DOC-T04` |
| `FR-DOC-03` | Quản lý version, chỉ công bố version đã SUCCESS; khi bản mới lỗi dùng bản thành công … | B4,H3 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T05` |
| `FR-DOC-04` | PRIMARY/ASSISTING được grant/revoke vào lớp theo quyền hiện hành; không sửa tệp nguồn… | B2,B6,O1 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T06`, `DOC-T07` |
| `FR-DOC-05` | Revoke chặn nguồn tại lần kiểm tra mới, không chỉ ẩn giao diện; cảnh báo trước xóa ng… | B6,B7 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T02`, `DOC-T08`, `DOC-T09`, `DOC-T10` |
| `FR-DOC-06` | Student/teacher lưu notes/bookmarks chỉ chủ sở hữu xem/sửa; giữ chữ tự viết và che qu… | G5,H6,L6,O2 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T11`, `DOC-T12`, `DOC-T13` |
| `FR-DOC-07` | Xử lý crash/retry không làm mất file gốc/previous successful version | H3,QAS-10 | 04_FRS_Document.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `DOC-T05` |
| `FR-LE-01` | Tách Practice, Assessment và Assignment, tách kết quả luyện tập khỏi điểm chính thức | D0,D3,D8 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T01` |
| `FR-LE-02` | Bốn loại câu hỏi: single, multiple, true/false, short answer | D2 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T01` |
| `FR-LE-03` | Nội dung assessment đã công bố bất biến; mỗi attempt gắn một đề version cụ thể | I4,O3 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T04`, `LE-T05` |
| `FR-LE-04` | PRIMARY duyệt công bố chính thức, sửa/hủy điểm nhạy cảm; ASSISTING chỉ thao tác theo … | D1,D4,D7,I6,M2,M4 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T01`, `LE-T02`, `LE-T03`, `LE-T11`, `LE-T13`, `LE-T14` |
| `FR-LE-05` | Lưu thành công câu trả lời từng phần, resume khi còn giờ; auto-submit khi hết giờ nhữ… | I1,I2 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T05`, `LE-T06`, `LE-T07`, `LE-T08` |
| `FR-LE-06` | Double submit/retry/timeout không nhân đôi attempt/submission/grade/evidence | QAS-03 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T09` |
| `FR-LE-07` | Late policy, resubmission, best/latest/average do giáo viên cấu hình trong giới hạn r… | I3,I5,M3,O5 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T15`, `LE-T16`, `LE-T17`, `LE-T18` |
| `FR-LE-08` | Người đã chuyển lớp vẫn có quyền giới hạn với kết quả/bài đã nộp/phúc khảo hợp lệ | L2,M1,O4 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T19`, `LE-T20`, `LE-T21`, `LE-T22` |
| `FR-LE-09` | Điểm cuối cùng của Assignment và câu chủ quan do giáo viên quyết định; sửa điểm lưu v… | D4,D5,I6,J3 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T10`, `LE-T11`, `LE-T12` |
| `FR-LE-10` | Learning là nguồn deadline chính thức; thay đổi deadline phát thông báo/bản chiếu lịc… | L3,O5 | 05_FRS_Learning.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LE-T17`, `LE-T23`, `LE-T24`, `LE-T25` |
| `FR-LI-01` | Nhận và đối soát learning evidence có provenance, version, idempotency; không lấy điể… | E3,J3 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T01`, `LI-T02`, `LI-T03`, `LI-T04` |
| `FR-LI-02` | Không kết luận mastery nếu thiếu evidence độc lập hoặc coverage; hiển thị “Chưa đủ dữ… | J1,J2,O6 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T05`, `LI-T06`, `LI-T07` |
| `FR-LI-03` | Student xem dữ liệu mình; teacher xem lớp được phân công; không lộ dữ liệu chat riêng… | E1,E2,E5 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T11`, `LI-T12` |
| `FR-LI-04` | Gợi ý tự nguyện, giải thích được căn cứ, không tự chấm/trừng phạt hoặc gắn nhãn cố đị… | E4,E6,J5 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T08`, `LI-T09`, `LI-T10` |
| `FR-LI-05` | Báo cáo aggregate PDF/Excel qua Admin, có school scope/redaction/audit | F6,O8 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T14`, `LI-T15`, `LI-T16` |
| `FR-LI-06` | Thống kê nhóm liên quan hoạt động AI nếu về sau được cung cấp phải ẩn nhóm dưới 5 và … | J4,O6 | 06_FRS_Intelligence.md, 10_LLD_Future.md — PROPOSED / NOT IMPLEMENTED | `LI-T13` |
| `NFR-SEC-01` | Authentication & session | Hash credential, HttpOnly cookie, CSRF/Origin, revoke session; Core-03 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-002`, `TC-003`, `TC-029` |
| `NFR-SEC-02` | Authorization | Không có data leak trên bộ thử cross-school/class/action, fail closed; QAS-04/Core-01 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-019`, `TC-021`, `DOC-T07`, `DOC-T09`, `LE-T03`, `LE-T13`, `LI-T10`, `LI-T16` |
| `NFR-SEC-03` | Privacy | Không log/chat/token trong audit/notification; policy data request; K1–K6 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-025`, `DOC-T04`, `TC-031` |
| `NFR-DI-01` | Data integrity | 0 duplicate/lost operations trên test concurrency có kiểm soát, QAS-03 1.000 case khi Learning triển khai | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-010`, `TC-023`, `LE-T09`, `LE-T24` |
| `NFR-PERF-01` | Performance | Class-list backend p95 ≤500ms trong TP-01; mục tiêu Learning riêng theo QAS-05 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-032` |
| `NFR-AV-01` | Availability/isolation | Lỗi service độc lập không kéo sập Core functions; các phép đo QAS-01/02 cần điều chỉnh phạm vi vì AI đang hoãn | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-033` |
| `NFR-REC-01` | Recoverability | Xử lý version lỗi/retry không mất nguồn thành công gần nhất; QAS-10 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `DOC-T05` |
| `NFR-SCAL-01` | Scale | 100 CCU / 10 lớp / 50 Student/lớp / 20 docs/lớp, TP-01; không tự nhận đã đạt 358 CCU | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-034` |
| `NFR-DEP-01` | Deployability | Web/Core CI, migration, health, Compose smoke và version trace | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-027`, `TC-030` |
| `NFR-MOD-01` | Modifiability | Thuật toán Intelligence thay mà không sửa logic chấm điểm Learning, QAS-09 | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `LI-T07` |
| `NFR-UX-01` | Accessibility & responsiveness | Bàn phím, nhãn trường, trạng thái tải/lỗi; browser/viewport test thuộc kế hoạch, chưa có mục tiêu WCAG chính thức | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-028` |
| `NFR-OBS-01` | Observability | Correlation ID, audit cấu trúc, version ghi trong evidence, health/readiness | 08_HLD.md, 14_Security_Privacy.md, 15_Operations.md, 16_Test_Plan.md — MIXED / SEE QAS | `TC-035` |

## 3. Traceability đến các nguồn chuẩn

| Source | Được chuyển thành | Chưa tạo ra kết luận gì? |
|---|---|---|
| Business Rules A/F/G/K/L/M/O | BRD, SRS Core, FRS Core, Core LLD, UC | Không có nghĩa mọi UI E2E đã nghiệm thu |
| Business Rules B/G5/H3/H6/O1/O2 | Document FRS/LLD, UC-11, DOC-T01..13 | Không có Document backend hay storage contract approved |
| Business Rules D/I/M/O3..5 | Learning FRS/LLD, UC-12/13, LE-T01..25 | Không có Learning backend, grade engine hoặc approval UI live |
| Business Rules E/J/F6/O6/O8 | Intelligence FRS/LLD, UC-14, LI-T01..16 | Không có model/evidence contract approved hay QAS-11 report |
| Quality Attributes QAS-01..11 | SRS NFR, HLD, TP | Những mục liên quan AI không được triển khai trong hồ sơ này |
| Core API Contract + ORM + migration | FRS Core, LLD Core, API map | Snapshot tại commit chỉ; behavior cần runtime evidence |

## 4. Coverage và gaps theo tài liệu

- Có **45 FR** và **12 NFR** trong bảng nguồn SRS được trích xuất.
- Thiết kế **89 test case** tổng cộng, chưa chạy.
- Requirement chưa có case ID gắn trực tiếp trong test catalog: Không có.
- Những coverage gaps là đầu việc bổ sung test khi chốt scope, không được tự tick PASS.

## 5. Mẫu truy vết khi code

```yaml
requirement_id: FR-CL-03
business_rules: [A1, F2]
source_commit: <revision>
design: 09_LLD_Core.md
api_contract: docs/architect/microservices-v1/core/API_CONTRACT.md
code_paths: []
test_cases: [TC-012, TC-015]
test_run_evidence: []
verification_status: NOT_RUN
owner_acceptance: PENDING
```

## 6. Quy trình cập nhật RTM

1. Khi nghiệp vụ thay đổi, xác định Rule ID và làm Change Request.
2. Cập nhật FR/NFR/UC và design trước khi code; đánh dấu PROPOSED với quyết định chưa chốt.
3. Sửa code/schema/API rồi thêm regression case và artifact trên revision mới.
4. QA liên kết evidence vào RTM theo test case và report thật.
5. Chỉ sau human approval mới đổi Acceptance status, không dùng CI thay sự chấp thuận nghiệp vụ.