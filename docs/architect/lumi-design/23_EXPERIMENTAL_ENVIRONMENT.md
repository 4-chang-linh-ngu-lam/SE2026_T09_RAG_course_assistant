# PHẦN C — MÔI TRƯỜNG THỰC NGHIỆM VÀ PHƯƠNG PHÁP ĐÁNH GIÁ

**Mã:** LUMI-EXP-002 · **Phiên bản:** 2.0-DRAFT · **Đối tượng:** QA, người phản biện, DevOps, giảng viên chấm đồ án.  
**Nguyên tắc:** phân biệt `MỤC TIÊU KIỂM THỬ`, `CẤU HÌNH THỰC NGHIỆM ĐÃ GHI`, `KẾT QUẢ TỪ REPO`, `CHƯA CHẠY`. Không biến số kế hoạch thành kết quả.

## C1. Tại sao cần một chương thực nghiệm tách biệt?

Một báo cáo thiết kế có thể đúng về logic nhưng vẫn thiếu căn cứ về **hệ thống chạy được**, **tải bao nhiêu**, **môi trường nào**, **chạy phép thử nào** và **đo lường có tái lập được hay không**. Chương này quy định quy trình ghi bằng chứng để một người khác có thể chạy lại độc lập.

### C1.1. Phạm vi thực nghiệm hiện tại

- **Core phía máy chủ**: PostgreSQL 16, FastAPI, các module Identity/Classroom/Social/Notification/Administration và test suite tự động.
- **Web live**: Next.js build/contract integration; browser E2E cần kiểm tra riêng trên môi trường chạy thật.
- **Compose**: khởi động DB, migration, API, worker, Web; smoke và fault injection DB outage.
- **Khả năng chịu tải**: Core-06 class-list subset, không bao gồm Document/AI/Learning/LI.
- **Không thực nghiệm AI Service**: chưa có thiết kế; không mô phỏng chất lượng RAG như kết quả của hệ thống.

![A14 - Chuỗi môi trường thực nghiệm](diagrams_arch/A14_Experimental_Environments.png)

## C2. Cấu hình môi trường phải lưu cùng kết quả

| Thông số | Giá trị/nguồn baseline | Bắt buộc ghi trong report mới |
|---|---|---|
| Source commit | `55324dc` là mốc tài liệu, không phải runtime vừa đo | Full SHA, branch, dirty working tree? |
| OS runner | GitHub Actions `ubuntu-latest`; local tùy máy | Distribution/version, architecture |
| Python | CI 3.12 | Exact patch version + pip freeze/lock |
| Node | CI 22 | Exact patch/npm version |
| PostgreSQL | Compose/CI `postgres:16-alpine` | `SELECT version()`, migration `alembic heads` |
| Core | FastAPI + SQLAlchemy + Alembic | Image digest / application release SHA |
| Database pool | Compose local 5+10 overflow, timeout 3 s | Pool size/overflow actual |
| Web | Next.js live mode | Build ID/revision, URL origin |
| SMTP | Khác nhau theo môi trường | Provider giả/thật, không ghi secret/token |
| Network | Local loopback hoặc public staging | Region, RTT, DNS/TLS, network route |
| Dataset | Synthetic fixture | Seed command, dataset manifest SHA, counts |
| CI evidence | JUnit/coverage/rule-evidence | Run ID, path, downloadable artifact checksum |
| Thời gian đo | Core-06 600s + warmup 30s theo pipeline | Start/end ISO UTC, warmup, samples |

Không công bố hostnames nội bộ, private database connection string hoặc token thật trong tài liệu chia sẻ. Report công khai nên chứa **đường dẫn evidence đã lọc** và `hash` của cấu hình phi nhạy cảm.

## C3. Mô hình thực nghiệm E1 — chức năng Core

### C3.1. Mục tiêu

Kiểm tra quy trình xử lý end-to-end có **real database**, không dùng adapter mock cho chức năng đánh giá.

### C3.2. Dữ liệu giả lập chuẩn

- Một School giả lập hợp lệ với Admin đang ACTIVE.
- Năm học/học kỳ/khối 6–12; ít nhất một homeroom và một subject class AUTO, một class MANUAL.
- Tài khoản PRIMARY, ASSISTING, Student ACTIVE/PENDING/LOCKED; học sinh có hoặc không có membership.
- Có bài đăng, bình luận, CORE calendar event, notification V2 và tối thiểu một tình huống `409` stale version.
- Có dữ liệu `data_requests` nhưng DELETE vẫn `IN_REVIEW` nếu thiếu executor được duyệt.

Tạo fixture bằng **CLI dev/test có guard** theo `services/core/migrations/README.md`, không viết script tự tạo Admin bypass auth vào DB thật. Mọi tên/email/username dùng giả lập; không copy danh sách học sinh của trường.

### C3.3. Bộ kịch bản căn bản

| Mã | Luồng | Tiền điều kiện | Kết quả mong đợi | Bằng chứng |
|---|---|---|---|---|
| EXP-F01 | Student activation | Admin tạo user pending | Mã một lần → ACTIVE; replay bị chặn | HTTP, DB state, audit redacted |
| EXP-F02 | Staff invitation/recovery | SMTP staging có cấu hình | Worker gửi; redeem làm ACTIVE, token không lộ log | Mail receipt metadata + event status |
| EXP-F03 | Admin tạo class AUTO | Roster/PRIMARY hợp lệ | Class xuất hiện cho teacher/student đúng lớp | Screenshot browser, API, DB |
| EXP-F04 | MANUAL roster | User khác trường, user đúng trường | Cross-school denied; roster đúng; không sync AUTO giả | API + membership query |
| EXP-F05 | Feed/comments/calendar | Lecturer/Student hợp lệ | Đúng action permissions; Student không tạo calendar event | HTTP 2xx và deny 403/404 |
| EXP-F06 | Notification | V2 recipient snapshot | Chỉ recipient đúng nhận; read/read-all idempotent | Worker log metadata + inbox DB |
| EXP-F07 | Archive/restore | Admin/teacher/student | Admin được thực hiện, Lecturer/Student không; activity mới bị chặn archive | Auth matrix + current state |
| EXP-F08 | Data request | ACCESS/EXPORT/CORRECTION/DELETE | Chính sách hiện hành áp dụng; DELETE không COMPLETED giả | Request/audit state |
| EXP-F09 | Concurrent stale updates | Hai phiên Admin cùng chỉnh roster | Version conflict 409, không mất ghi danh lịch sử | PostgreSQL state + requests |
| EXP-F10 | Web live failure | Tắt Core tạm thời | Web báo upstream unavailable, không nhận dữ liệu mô phỏng dùng kiểm thử | Browser/network HAR redacted |

Kết quả expected phải dựa trên Core contract hiện hành. Khi contract dùng 404 để che tài nguyên ngoài quyền, không ép test đòi 403.

## C4. Mô hình thực nghiệm E2 — hiệu năng Core

### C4.1. Mục tiêu QAS-05 và phép thử lịch sử

QAS-05 đặt mục tiêu **p95 phía máy chủ danh sách lớp ≤ 500ms** với TP-01. Đây là mục tiêu; tỷ lệ thành công target ≥ 99% cho các request hợp lệ trong tập đo. Các yêu cầu về assessment/save/analytics không thuộc hệ thống Core hiện có, nên chưa được đánh dấu đã đo.

**Báo cáo Core-06 lưu trong repo ngày 30/10/2026:** 58.521/58.521 HTTP 200, phía máy chủ p95 ~21,84ms, client loopback p95 ~672,04ms, scope mismatch 0. Cấu hình máy được báo cáo là VM/provider-shared, host-side CPU/RAM chưa đo; không đại diện ở phía người dùng p95 Cloud Run hoặc tính năng sản phẩm đầy đủ. `full_tp01_verified=false`.

### C4.2. Quy trình tái lập (chưa chạy trong đợt viết tài liệu)

1. Dùng PostgreSQL test mới và migration head; tạo 10 classes và 500 Students giả lập theo script chính thức.
2. Định nghĩa generator gồm 100 users, tách request count/timing server và client. Warmup 30s rồi 600s đo.
3. Ghi exact CPU/RAM/OS/DB pool/connection latency; dừng những mô hình tải không thuộc phép thử hoặc đo và báo cáo tác động cạnh tranh.
4. Chạy script `services/core/tests/performance/class_list_load.py` theo runner/CLI được mô tả trong test README; không chạy lên production database.
5. Xuất raw results/histogram latency, success rate, scope mismatch, phía máy chủ p50/p95/p99, client p50/p95/p99, max.
6. Bổ sung `db_pool_wait`, DB slow queries, CPU/RAM mỗi process và worker backlog (nếu công cụ đã hỗ trợ). Không sửa code đo rồi dùng số cũ để kết luận.
7. Kết luận riêng cho **Core class-list**; không coi đó là kết quả mixed mô hình tải của cả Lumi.

### C4.3. Tiêu chuẩn diễn giải

- **`PASS`** chỉ khi mô hình tải, environment, target và measurement tương ứng; nếu không có CPU/RAM hoặc network facts mà threshold cần, báo `PARTIAL`.
- **p95 không bằng trung bình**: ít nhất 95% mẫu đáp ứng không quá ngưỡng, mẫu đủ lớn và cách đo phải ghi rõ.
- **Phía máy chủ vs end-user p95**: server ASGI elapsed time khác với browser round-trip, cold start, TLS, UI hydrate, JS render, SMTP queue delay.
- **358 CCU** là yêu cầu dự án trước đó, **không** có bằng chứng trong báo cáo Core-06 hiện hành; nếu được giữ làm target, phải định nghĩa mô hình tải 358 CCU và cách đo riêng.

## C5. Mô hình thực nghiệm E3 — lỗi có kiểm soát / fault injection

| Mã | Lỗi chèn | Thao tác đo | Kết quả kỳ vọng | Trạng thái bằng chứng |
|---|---|---|---|---|
| EXP-R01 | Dừng PostgreSQL trong Compose | `/health/ready` và `/health/live` | ready 503; live còn 200 khi process sống | CI `compose-smoke` có kịch bản |
| EXP-R02 | Restart notification worker | Tạo outbox event V2 trước restart | Không mất recipient; không nhân đôi inbox | Core test đã có, browser E2E cần riêng |
| EXP-R03 | Event V1 không recipient snapshot | Worker --once | Không phát theo audience hiện hành | Policy hiện hành, test/phía máy chủ evidence |
| EXP-R04 | SMTP timeout sau khi provider có thể đã nhận thư | Recovery retry | Không lộ token; recipient có thể nhận mail duplicate, token semantics giữ | Staging test một phần, provider semantics cần ghi rõ |
| EXP-R05 | Token revoked/locked | Reuse access/refresh token cũ | Reject theo auth state thực | Identity tests |
| EXP-R06 | Core API offline lúc browser mutate | Web form | Thông báo lỗi kết nối, không báo thành công giả | Cần browser E2E lưu evidence |
| EXP-R07 | Ngắt mạng sau submit có commit | Retry qua idempotency | Không tạo record trùng trong scope supported | Theo từng endpoint; process-local limitation |
| EXP-R08 | Không có tài liệu/learning service | Click route chưa có phía máy chủ | UI trạng thái unavailable, không fallback mock production | Registry và browser test |

**Chú ý:** một số test ở bảng được tham chiếu từ repository, một số là **test phải chạy**, không viết `PASS` khi không có test report tương ứng.

## C6. Mô hình thực nghiệm E4 — bảo mật, phân quyền và privacy

- Role matrix: ADMIN/LECTURER/STUDENT; current school scope; PRIMARY vs ASSISTING; LOCKED vs ACTIVE; archived vs active.
- Bypass UI: trực tiếp gọi Core API với sửa `class_id`, `student_id`, `post_id`, `notification_id`, `school_id` không cấp quyền.
- Token/session: refresh replay, logout-all, password reset/activation expiry, cookie Secure/SameSite, Origin/CSRF.
- Shared data: Admin thuộc trường A không được xem danh sách user hoặc audit của trường B; Student không đọc notification của user khác.
- Confidentiality: không lấy raw chat trong admin audit, không in one-time code/password trong CI logs hoặc screenshot.
- Data request: ACCESS/EXPORT/CORRECTION cần người có thẩm quyền xác minh/attest; DELETE cần policy và executor riêng; audit hiện hành không đồng nghĩa xử lý toàn bộ liên service.

**Bằng chứng cần lưu:** bảng `case ID → input role/state → expected HTTP/status code → observed → screenshot/HAR → commit/revision → PASS/FAIL`. Không lưu access JWT thật, request password body hoặc mã kích hoạt không che.

## C7. Môi trường thực nghiệm browser E2E

### C7.1. Điều kiện trước phép thử

1. Chọn **một** Web environment có `NEXT_PUBLIC_DATA_MODE=live` và Core tương thích.
2. Xác nhận `WEB_ORIGIN` là origin public đúng với browser, `CORE_API_URL` là upstream server-side, `CORS_ORIGINS` và `PUBLIC_WEB_URL` khớp theo hợp đồng.
3. Đăng nhập Admin/Teacher/Student giả lập; không dùng dữ liệu thật.
4. Xác định migration head và Core/web source image.
5. Tắt/không dùng `dev:mock` trong phép đo live E2E; chụp network response thật và DB state.

### C7.2. Script trải nghiệm tối thiểu

1. Admin đăng nhập → mở user list/search và class catalog.
2. Admin tạo Student → lấy mã một lần → Student activate → Student login.
3. Admin tạo homeroom/roster, tạo subject class AUTO, assign PRIMARY/ASSISTING.
4. Lecturer đăng nhập, mở đúng class, đăng post, tạo CORE calendar.
5. Student đăng nhập, đọc post, bình luận, xem lịch và notification.
6. Admin thay roster/archive; Student/Teacher reload và quyền cập nhật đúng (không rò nội dung lớp mới/khác scope).
7. Thực hiện ít nhất các ca 401/403/404/409/422 và network outage.
8. Kiểm tra browser console, a11y/viewport cơ bản và không có secret/PII ở bundle.

**Acceptance:** chỉ ghi `E2E PASS` khi tất cả luồng bắt buộc chạy qua runtime live có bằng chứng. Bộ screenshot mock hoặc `web-build` xanh chỉ được ghi `UI BUILD PASS`.

## C8. Biểu mẫu ghi nhận kết quả thực nghiệm

```text
EXPERIMENT ID: EXP-...
PURPOSE: ...
ENVIRONMENT: local / CI / staging / production mock
SOURCE: git SHA, branch, dirty=false/true
CORE IMAGE: sha256:...    WEB BUILD: ...
DATABASE: PostgreSQL version, migration head
HOST: CPU/RAM/OS, region, connection pool
DATASET: synthetic manifest SHA, class/student counts
PROCEDURE: exact commands/scripts, warmup, duration
MEASUREMENT: backend/client timings; status counts
OBSERVED RESULTS: raw numbers, charts/evidence links
COMPARISON: objective -> pass/fail/partial
KNOWN LIMITS: provider-shared machine, no real end-user network, etc.
REVIEW: reviewer + UTC date + open bugs
```

## C9. Đồ án và nghiên cứu phải trình bày gì trước hội đồng?

- Phân biệt **mục tiêu hệ thống** và **đo đạc hệ thống đã triển khai**.
- Có bảng công nghệ thực, phiên bản, topology và cấu hình máy/hạ tầng theo từng phép thử.
- Các sơ đồ phải có chú giải, chiều luồng, protocol, service owner và trạng thái Current/Target.
- Có test coverage chức năng, boundary tests, concurrency tests, error handling và browser E2E.
- Có security/privacy assumptions và RPO/RTO chưa duyệt; không tự viết “đáp ứng 24/7” hay “0 lỗi bảo mật”.
- Không có phần thực nghiệm AI Service do scope hoãn nghiên cứu.

**Nguồn nội bộ:** `QUALITY_ATTRIBUTES.md`, `TASK-015`, `services/core/tests/README.md`, `core-ci.yml`, Core API Contract, Web integrations registry và `tasks/README.md`. Chương này đặt ra **phương pháp đánh giá**, không giả vờ cung cấp phép đo mới chưa chạy.