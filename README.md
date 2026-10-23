# RAG Course Assistant — SE2026-T09

Dự án trợ giảng học tập sử dụng **Microservices trong một GitHub Monorepo**, nhóm 4 thành viên.

**Năm service:** Core, Document, Learning, AI, Learner Intelligence. **Core-first:** hoàn thiện toàn bộ Core (auth, lớp/thành viên, feed, comments, calendar, notifications, quản trị/audit) rồi mới sang Document + AI, Learning và Learner Intelligence.

**Core stack đã chọn:** Next.js (Web), FastAPI (Core), PostgreSQL, Docker Compose. Các service khác chỉ chốt ranh giới và giao tiếp ở giai đoạn này; không suy diễn stack hay schema riêng.

## Đọc tài liệu
1. [Business Rules](docs/architect/BUSINESS_RULES.md) — nguồn nghiệp vụ.
2. [ADR](docs/architect/microservices-v1/ADR-001.md), [Architecture](docs/architect/microservices-v1/ARCHITECTURE.md) — kiến trúc.
3. [Core Design](docs/architect/microservices-v1/core/DESIGN.md), [Core API](docs/architect/microservices-v1/core/API_CONTRACT.md), [Folder Structure](docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md) — triển khai Core.
4. [Danh mục task](tasks/README.md) — hiện trạng, việc cần sửa và phụ thuộc của TASK-001–020 (rà soát 2026-10-16).
5. [Roadmap](docs/architect/microservices-v1/IMPLEMENTATION_ROADMAP.md), [Quality Attributes](docs/architect/microservices-v1/QUALITY_ATTRIBUTES.md), [Contributing](docs/CONTRIBUTING.md).

**Trạng thái:** Core đã triển khai Identity, Classroom, Social/Calendar, Notification và Administration/import; Web nối **63 API đã duyệt**. [Nghiệm thu chức năng gần nhất](apps/web/docs/CORE_WEB_CONNECTION_FIXES_2026-10-23.md): 324 test Web, build live, 22 nhóm HTTP và 5 nhóm thao tác Chrome đạt. Đây không phải chứng nhận toàn bộ năm service hoặc mục tiêu hiệu năng. Xem [API matrix](apps/web/docs/CORE_API_MATRIX_2026-10-22.md) và [Core README](services/core/README.md).

<a id="core-web-demo"></a>

## Chạy demo Core–Web để cả nhóm kiểm thử

Demo dùng backend và database thật, dữ liệu giả lập, không phải chế độ mock UI. Cần Docker Desktop đang chạy Linux containers, Docker Compose v2 và PowerShell. Chạy các lệnh dưới đây từ thư mục gốc repository trên nhánh `core_full`.

### Tài khoản Admin demo công khai

| Mục | Giá trị |
|---|---|
| Web | http://localhost:3100/login |
| Email Admin | `admin@seed.example.com` |
| Mật khẩu demo | `LumiDemoOnly!2026` |
| Swagger / readiness | http://localhost:8100/docs / http://localhost:8100/health/ready |
| Database riêng | `dev_lumi_demo`, project Compose `lumi-core-demo` |

Đây là **thông tin test công khai**, chỉ tạo khi chủ động chạy seed trên database demo riêng. Không dùng cho dữ liệu thật hoặc môi trường công khai. Clone Git không mang theo database hay tài khoản đang chạy trên máy thành viên khác. Mật khẩu này không thay đổi Admin trên Web `3000`/database dev có sẵn; tài khoản ở đó giữ mật khẩu đã đặt riêng. Ứng dụng không tự tạo Admin khi khởi động.

### 1. Tạo cấu hình demo riêng, không ghi đè môi trường có sẵn

Khối này chỉ chạy lần đầu. `.env.demo` được Git bỏ qua; chứa các key và mật khẩu database ngẫu nhiên riêng của máy, không đưa lên Git. Các cổng `3100`, `8100`, `55433` tách khỏi môi trường dev thường dùng; nếu đang bị chiếm, chọn cổng khác và sửa đồng bộ `WEB_ORIGIN`/`CORS_ORIGINS`.

```powershell
if (Test-Path .env.demo) { throw '.env.demo da ton tai; dung lai file do, khong ghi de.' }
function New-DemoSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
    return ([BitConverter]::ToString($bytes)).Replace('-', '').ToLowerInvariant()
}
$dbPassword = New-DemoSecret
$jwtKey = New-DemoSecret
$internalKey = New-DemoSecret
$proxyKey = New-DemoSecret
$demoConfig = @"
POSTGRES_DB=dev_lumi_demo
POSTGRES_USER=lumi_demo
POSTGRES_PASSWORD=$dbPassword
DATABASE_URL=postgresql+psycopg://lumi_demo:${dbPassword}@db:5432/dev_lumi_demo
POSTGRES_PORT=55433
CORE_PORT=8100
WEB_PORT=3100
WEB_ORIGIN=http://localhost:3100
CORS_ORIGINS=["http://localhost:3100"]
COOKIE_SECURE=false
NEXT_PUBLIC_DATA_MODE=live
CORE_IMAGE=lumi-core-demo:local
SECRET_KEY=$jwtKey
INTERNAL_SERVICE_SECRET=$internalKey
CORE_PROXY_SECRET=$proxyKey
"@
[IO.File]::WriteAllText((Join-Path (Get-Location) '.env.demo'), $demoConfig, [Text.UTF8Encoding]::new($false))
```

### 2. Dựng stack và tạo tài khoản/dữ liệu mẫu

Các biến môi trường đã export trong terminal có thể được Compose ưu tiên hơn file; dùng terminal mới và chỉ đặt `CORE_SEED_ADMIN_PASSWORD` như dưới đây. Chạy `docker compose ... config --quiet` để kiểm tra cấu hình; tránh in toàn bộ cấu hình có secret vào log.

```powershell
docker compose --project-name lumi-core-demo --env-file .env.demo config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cau hinh Compose khong hop le.' }
docker compose --project-name lumi-core-demo --env-file .env.demo up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Stack demo chua san sang; kiem tra docker compose ps/logs.' }
$previousSeedPassword = $env:CORE_SEED_ADMIN_PASSWORD
try {
    $env:CORE_SEED_ADMIN_PASSWORD = 'LumiDemoOnly!2026'
    docker compose --project-name lumi-core-demo --env-file .env.demo exec -T -e CORE_SEED_ADMIN_PASSWORD core python -m app.maintenance seed-dev --environment development --expected-database dev_lumi_demo --school-id d4b55a29-6aae-4f9b-b6b1-d0e44ab2c990 --school-name 'Lumi Public Local Demo'
    if ($LASTEXITCODE -ne 0) { throw 'Seed bi tu choi; khong xoa database de ep seed.' }
} finally {
    $env:CORE_SEED_ADMIN_PASSWORD = $previousSeedPassword
}
```

Seed lần đầu trả `created:true`; chạy lại cùng profile trả `created:false`, không reset mật khẩu hoặc dữ liệu đã sửa. Nếu database không rỗng và không có marker seed, lệnh từ chối. Không chạy seed lên database đang dùng hoặc xóa volume của người khác để thử lại.

Runbook đã được chạy thực tế ngày 23/10/2026: dựng stack từ các khối lệnh trên, seed lần đầu và lặp lại, Admin đăng nhập qua Web, cấp mã/reset/đăng nhập Học sinh, đọc đúng 2 lớp theo quyền và từ chối trang Admin với `403`. Môi trường dev cũ vẫn trả `200` ở Web login/Core readiness. Luồng Giáo viên qua SMTP ngoài vẫn cần cấu hình và kiểm chứng riêng.

Dữ liệu có sẵn: 1 Admin, 2 giáo viên, 3 học sinh; 7 lớp hành chính khối 6–12; 14 lớp Toán AUTO/MANUAL. `seed.student.1` và `.2` thuộc roster `Seed 9A`; `.1` còn ở `Seed Math 9 MANUAL`. Giáo viên `primary@seed.example.com` và `assisting@seed.example.com` đã được phân công. **Chỉ Admin có mật khẩu demo nói trên.** Mật khẩu ngẫu nhiên của các tài khoản còn lại không được lưu/bàn giao; dùng quy trình cấp mã hoặc mời/reset ở dưới.

Mở http://localhost:3100/login, chọn đăng nhập nhân sự và dùng Admin demo. Nếu vừa dựng xong mà Web chưa phản hồi, chờ vài giây rồi tải lại. `localhost` dùng chung cookie giữa các cổng: thử demo `3100` và dev `3000` bằng các profile trình duyệt khác nhau; mỗi vai trò dùng một cửa sổ/profile riêng để tránh ghi đè phiên refresh.

### 3. Luồng Admin: tài khoản → roster → lớp → quyền

1. Vào **Danh sách tài khoản** (`/admin/accounts`), kiểm tra sáu tài khoản seed và mở chi tiết; tải lại trang để xác nhận dữ liệu từ backend.
2. Vào **Danh mục học vụ** (`/admin/catalog`) và **Lớp hành chính** (`/admin/homerooms`), xem năm `2026-2027`, học kỳ `1`, môn `SEED-MATH`, lớp `Seed 9A` và hai học sinh trong roster.
3. Vào **Lớp môn học** (`/admin/classes`), mở `Seed Math 9 AUTO` và `Seed Math 9 MANUAL`; kiểm tra giáo viên chính/phối hợp và danh sách thành viên.
4. Thử cấp học sinh mới tại `/admin/accounts/students/new`, lưu username/mã một lần vừa hiển thị. Học sinh không có màn hình tự đăng ký hoặc tự join lớp.
5. Thêm học sinh mới vào lớp MANUAL. Với lớp AUTO, sửa roster rồi thực hiện preview/sync; xác nhận đúng phiên bản và số lượng tác động. Mutation có yêu cầu lý do phải chọn lý do trước khi lưu.
6. Dùng một lớp demo để thử lưu trữ: lớp chuyển chỉ đọc, không nhận bài/bình luận/sự kiện mới; khôi phục rồi thử lại. Không dùng lớp đang làm bước khác nếu chưa ghi lại thay đổi.
7. Kiểm tra `/admin/audit` sau các thao tác. Mở hai tab sửa cùng tài nguyên để thử xung đột phiên bản: tải lại/preview lại khi có `409`, không gửi lại mù.

### 4. Luồng Học sinh: kích hoạt/reset → vào lớp → feed → lịch

1. Để thử tài khoản đã có lớp: Admin mở `seed.student.1`, chọn **Cấp mã kích hoạt học sinh một lần** với mục đích đặt lại mật khẩu; lưu mã vừa hiển thị.
2. Trong profile trình duyệt riêng, mở http://localhost:3100/reset-password, nhập mã và đặt mật khẩu của bạn. Sau đó vào `/login`, chọn **Học sinh**, đăng nhập bằng `seed.student.1` và mật khẩu vừa đặt.
3. Để thử kích hoạt lần đầu: Admin cấp mã cho `seed.student.3` hoặc học sinh mới tạo; người học vào `/activate`, nhập username/mã và tự đặt mật khẩu. Admin ghi danh vào lớp MANUAL trước khi thử nội dung lớp.
4. Từ trang chủ/danh sách lớp, mở lớp khối 9 → Tổng quan → Bảng tin. Tạo bài, sửa bài mình, bình luận, sửa bình luận; tải lại trang và kiểm tra dữ liệu vẫn còn. Học sinh không sửa bài của người khác hoặc vào trang quản trị.
5. Mở lịch và thông báo; thử đánh dấu một thông báo rồi tất cả là đã đọc. Inbox chỉ có dữ liệu khi có sự kiện nghiệp vụ; worker `notification-worker` cần đang chạy.
6. Giữ cửa sổ học sinh mở; Admin khóa tài khoản đó. Request kế tiếp của học sinh phải bị từ chối. Mở khóa rồi đăng nhập lại; không kỳ vọng phiên cũ tự phục hồi.

### 5. Luồng Giáo viên: mời qua email → phân công → feed/lịch

Luồng thủ công này cần SMTP hợp lệ. Demo mặc định không cấu hình SMTP và các email `@seed.example.com` không phải hộp thư để nhận thư. Không có mật khẩu giáo viên dùng chung hoặc chức năng lấy raw token từ DB.

1. Đặt `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_SECURITY` và thông tin xác thực cần thiết trong `.env.demo` riêng; dùng SMTP/hộp thư bạn kiểm soát. Dựng lại service Core bằng cùng lệnh Compose. Xem [cấu hình SMTP](services/core/README.md).
2. Admin vào `/admin/accounts/staff/invitations`, mời giáo viên bằng email nhận được thư. Người nhận mở `/staff/invitation` và dùng token từ email để tự đặt mật khẩu.
3. Admin mở cấu hình một lớp demo, phân công giáo viên mới vào lớp. Trong profile riêng, giáo viên đăng nhập nhân sự, xem lớp phụ trách, tạo/sửa bài và bình luận; tải lại trang để kiểm tra lưu thực.
4. Mở lịch lớp, tạo sự kiện, sửa thời gian/tiêu đề, tải lại rồi xóa. Thu hồi phân công từ Admin và kiểm tra lần đọc/ghi tiếp theo bị từ chối theo quyền hiện hành.
5. Nếu chưa có SMTP, dùng bộ test tích hợp mục 8: fixture TLS email riêng thực sự kiểm tra luồng mời/đặt mật khẩu và thao tác giáo viên, không gửi thư ra ngoài.

### 6. Luồng import và yêu cầu dữ liệu

1. Tạo file CSV UTF-8 thử nghiệm, không dùng thông tin cá nhân thật:

   ```csv
   username,display_name
   demo.import.01,Demo Student 01
   demo.import.02,Demo Student 02
   ```

2. Admin vào `/admin/imports/new` → chọn file → xem preview/lỗi → chọn lý do → xác nhận. Kiểm tra hai tài khoản mới trong danh sách; dùng username khác nếu đã import trước đó. Thử file có username trùng để kiểm tra báo lỗi và không tạo thành công giả. Import tối đa 100 dòng dữ liệu, file tối đa 2 MB; XLSX chỉ một sheet, không công thức.
3. Học sinh gửi yêu cầu dữ liệu trong hồ sơ/tài khoản; Admin vào `/admin/data-requests`, mở và xử lý theo lựa chọn backend cho phép. Executor xuất/xóa dữ liệu liên service và download chưa có hợp đồng: không kỳ vọng nhận được file chỉ vì đã duyệt.

### 7. Kiểm tra lỗi mạng và giới hạn phạm vi

- Trong DevTools Network, bật Offline khi lưu một bài thử; tắt Offline rồi dùng thao tác tải lại/đối soát mà màn hình cung cấp. Xác minh dữ liệu server trước khi tự quyết định gửi lại; ứng dụng không tự replay mutation có kết quả chưa rõ.
- Core live hiện có tài khoản, lớp, ghi danh/phân công, feed/bình luận, lịch, thông báo, import và audit. AI Tutor, tài liệu, bài tập/quiz, điểm và Intelligence chờ service tương ứng; trạng thái chưa kết nối ở đó không phải một ca Core đã đạt.
- Chưa có API cho lịch sử/gửi lại/thu hồi lời mời, lịch sử import hoặc tải bản sao dữ liệu. Không dùng dữ liệu mock để xác nhận các chức năng này.
- Nếu vừa đăng nhập đã thỉnh thoảng `401`, kiểm tra giờ Windows/WSL theo [runbook Core](services/core/README.md), không bỏ kiểm tra JWT để thử cho qua.

### 8. Chạy kiểm thử tự động và dừng demo

Với Node 22.17+ và dependencies Web đã cài, chạy trong `apps/web`:

```powershell
npm.cmd run check
$env:CORE_BROWSER_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
try { npm.cmd run test:core } finally { Remove-Item Env:\CORE_BROWSER_EXECUTABLE -ErrorAction SilentlyContinue }
```

Nếu máy chưa có dependencies, chủ động chạy `npm.cmd ci` trong `apps/web` trước; nếu không dùng Chrome thì bỏ biến `CORE_BROWSER_EXECUTABLE` và chỉ nghiệm thu HTTP/render. Runner dùng stack, port, mật khẩu ngẫu nhiên và dữ liệu riêng; không dùng Admin demo này. Xem [Web README](apps/web/README.md) cho yêu cầu và chi tiết. Kết quả gần nhất: 324 test Web, 22 nhóm HTTP và 5 nhóm Chrome đạt; không suy ra mọi route hoặc SMTP ngoài đã được kiểm chứng.

Tại root, dừng riêng demo và giữ dữ liệu để hôm sau chạy lại:

```powershell
docker compose --project-name lumi-core-demo --env-file .env.demo down
# Lan sau: docker compose --project-name lumi-core-demo --env-file .env.demo up -d --wait
```

Không thêm `--volumes` nếu muốn giữ tài khoản và dữ liệu đã test. Không commit `.env.demo`, mã kích hoạt/reset, token, file mật khẩu riêng hoặc dữ liệu cá nhân thật.

## Phạm vi sản phẩm Lumi
Lumi phục vụ **học sinh THCS và THPT (khối 6–12)** trong **lớp học chính khóa**. Tiểu học, đại học và lớp học thêm không thuộc phạm vi MVP. Giao diện hướng đến học sinh phổ thông, giữ phong cách sáng, gọn, không game hóa hoặc trang trí quá mức.

**Stakeholder/role không mở rộng:** Admin, Lecturer (hiển thị là **Giáo viên**) và Student (hiển thị là **Học sinh**); nhà trường nhận báo cáo thông qua Admin, không có tài khoản riêng. Các enum `LECTURER`/`STUDENT` hiện hành tiếp tục được giữ để tương thích với code và API. Không mặc định có vai trò Phụ huynh hay Admin theo trường.

**Nguồn quyết định:** 20 quyết định đã được hợp nhất vào `docs/architect/BUSINESS_RULES.md`; API/schema mới phải được phân biệt rõ với Identity legacy đã triển khai. Không suy ra tính năng đã hoàn thành chỉ từ tài liệu.


## Phạm vi nghiệp vụ Lumi (baseline 2026-10-14)
MVP dành cho lớp chính khóa THCS/THPT khối 6–12 tại một trường, chuẩn bị school_id cho mở rộng; giữ 5 service và ba role ADMIN/LECTURER/STUDENT. Admin tạo lớp môn học liên kết lớp hành chính, phân công giáo viên và quản lý ghi danh AUTO/MANUAL; không có join code hoặc tự đăng ký Student trong MVP. Student nhận username và mã kích hoạt một lần từ Admin. Dữ liệu học tập cá nhân và chat lịch sử được bảo vệ khi chuyển lớp; nguồn tài liệu vẫn kiểm tra quyền hiện hành. Quản trị MVP có nhập CSV/Excel, yêu cầu dữ liệu xử lý có kiểm soát. **Đây là baseline mục tiêu, không phải tuyên bố mọi chức năng đã triển khai.** Xem `docs/architect/BUSINESS_RULES.md`.
