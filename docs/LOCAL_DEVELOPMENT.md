# Mã nguồn, khởi động và trải nghiệm Core–Document

Hướng dẫn cho nhánh `core_full`, cập nhật 24/10/2026. Core và Document đã nối live với Web; AI/RAG, Learning và Learner Intelligence chưa nằm trong bản chạy này. Nguồn nghiệp vụ là [Business Rules](architect/BUSINESS_RULES.md); không suy ra tính năng hoàn thành từ giao diện preview.

Ngày 24/10 đã chạy thử các lệnh bên dưới trên project Docker demo mới: build, migration, seed lần đầu và seed lặp lại, đăng nhập Admin qua Web, đọc 14 lớp và gọi Document qua proxy có xác thực đều đạt. Sau kiểm tra đã dừng project và giữ volume. Luồng gửi Gmail thật cần cấu hình SMTP riêng theo hướng dẫn; lượt kiểm tra này không gửi thư thật.

## 1. Đọc và sửa mã nguồn ở đâu

| Thư mục | Trách nhiệm / điểm bắt đầu |
|---|---|
| `apps/web/app/` | Next.js routes/layout; các page giữ mỏng, proxy server tại `app/api/` |
| `apps/web/src/features/` | UI và controller theo tính năng: identity, classroom, social, notification, administration, document |
| `apps/web/src/lib/data/port.ts` | Port chung của frontend; feature gọi adapter qua `src/lib/data/index.ts` |
| `apps/web/src/lib/data/live*.ts` | Kết nối dữ liệu thật; `live-identity` giữ session/refresh chung, `live-document` nối Document |
| `apps/web/src/lib/api/` | Allowlist, HTTP client, decoder và proxy; Core `/api/v1`, Document `/api/document/v1` |
| `apps/web/dev/mocks/` | Chỉ dành cho preview chủ động; không dùng làm fallback khi backend lỗi |
| `services/core/app/modules/` | Core.Identity, Classroom, Social, Notification, Administration; giao tiếp module qua public interface |
| `services/core/app/common/`, `bootstrap.py` | DB/auth/audit/outbox dùng chung và điểm đăng ký router |
| `services/core/app/maintenance/` | Seed dev có guard, báo cáo/mapping dữ liệu và bảo vệ downgrade |
| `services/document/app/` | API, xác thực qua Core, thư viện/phiên bản/grant, notes/bookmarks, private storage, extraction, worker/outbox |
| `services/*/migrations/` | Alembic riêng từng service; thêm revision mới, không sửa migration đã áp dụng |
| `apps/web/tests/`, `services/*/tests/` | Unit/contract/integration tests; browser/HTTP runner ở `apps/web/scripts/` |
| `docs/architect/microservices-v1/` | Thiết kế, API, event contract và ownership; Document có bộ tài liệu riêng |
| `compose.yaml` | PostgreSQL, Core, Web, worker; bật profile `document` cho Document bootstrap/migration/API/worker |

Một thay đổi điển hình: đọc Business Rule và contract → sửa backend trong module/service sở hữu → cập nhật contract nếu cần → thêm operation/decoder vào Web → nối live adapter → sửa feature/controller → chạy kiểm thử. Frontend không gọi fetch nghiệp vụ trực tiếp, không giữ service key, không tự cấp quyền. Backend luôn kiểm tra vai trò và quyền hiện hành theo lớp/tài nguyên. Xem [quy trình cộng tác và owner review](CONTRIBUTING.md).

## 2. Chuẩn bị

- Git, Docker Desktop đang chạy **Linux containers**, Docker Compose v2; có kết nối tải image/package lần đầu.
- Dùng **PowerShell**, không dán lệnh PowerShell vào Command Prompt. Để toàn bộ stack chạy bằng Docker, máy host không cần cài Python/Node.
- Khi sửa Web hoặc chạy frontend tests trên host: Node.js **22.17+**, npm; khi chạy runner backend: Python **3.12+** và Docker.
- Chạy các lệnh từ root repository, trừ khi có lệnh `Set-Location` riêng. Terminal mới giúp tránh biến môi trường cũ ghi đè cấu hình Compose.

```powershell
git clone --branch core_full https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant.git
Set-Location SE2026_T09_RAG_course_assistant
docker version
if ($LASTEXITCODE -ne 0) { throw 'Mo Docker Desktop va cho Linux engine san sang truoc khi tiep tuc.' }
docker compose version
```

Đã clone thì chuyển vào checkout hiện có; không clone đè và không đổi nhánh khi còn thay đổi chưa lưu.

## 3. Tạo cấu hình demo fullstack riêng

Demo này dùng project `lumi-fullstack-demo`, database `dev_lumi_fullstack_demo`. Tách khỏi dev đang chạy trên 3000/8000/8200 và demo Core cũ trên 3100/8100. Giữ cùng file cấu hình cho các lần chạy sau; thay mật khẩu trong file không tự thay credential của volume PostgreSQL đã tạo.

| Thành phần | Địa chỉ từ máy host |
|---|---|
| Web | http://localhost:3200/login |
| Core Swagger / readiness | http://localhost:8300/docs · http://localhost:8300/health/ready |
| Document Swagger / readiness | http://localhost:8400/docs · http://localhost:8400/health/ready |
| PostgreSQL | `localhost:55434`, thường không cần truy cập trực tiếp |

Tạo `.env.fullstack-demo` **một lần** bằng khối dưới. File bị Git bỏ qua, không chia sẻ hoặc commit. Các khóa, mật khẩu DB được sinh riêng cho máy; chỉ tài khoản Admin demo ở mục 5 có mật khẩu công khai theo chủ đích test.

```powershell
if (Test-Path .env.fullstack-demo) { throw 'File da ton tai; dung lai file, khong ghi de.' }
function New-FullstackDemoSecret {
    $demoBytes = New-Object byte[] 32
    $demoRandom = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $demoRandom.GetBytes($demoBytes) } finally { $demoRandom.Dispose() }
    return [BitConverter]::ToString($demoBytes).Replace('-', '').ToLowerInvariant()
}
$demoDbPassword = New-FullstackDemoSecret
$demoDocumentDbPassword = New-FullstackDemoSecret
$demoJwtKey = New-FullstackDemoSecret
$demoAccessKey = New-FullstackDemoSecret
$demoProxyKey = New-FullstackDemoSecret
$demoEventKey = New-FullstackDemoSecret
$demoSourceKey = New-FullstackDemoSecret
$demoJournalKey = New-FullstackDemoSecret
$demoConfiguration = @"
POSTGRES_DB=dev_lumi_fullstack_demo
POSTGRES_USER=lumi_fullstack_demo
POSTGRES_PASSWORD=$demoDbPassword
DATABASE_URL=postgresql+psycopg://lumi_fullstack_demo:${demoDbPassword}@db:5432/dev_lumi_fullstack_demo
DOCUMENT_DATABASE_URL=postgresql+psycopg://lumi_demo_document:${demoDocumentDbPassword}@db:5432/dev_lumi_fullstack_demo
POSTGRES_PORT=55434
CORE_PORT=8300
DOCUMENT_PORT=8400
WEB_PORT=3200
WEB_ORIGIN=http://localhost:3200
CORS_ORIGINS=["http://localhost:3200"]
COOKIE_SECURE=false
NEXT_PUBLIC_DATA_MODE=live
CORE_IMAGE=lumi-fullstack-demo-core:local
DOCUMENT_IMAGE=lumi-fullstack-demo-document:local
SECRET_KEY=$demoJwtKey
INTERNAL_SERVICE_SECRET=$demoAccessKey
CORE_PROXY_SECRET=$demoProxyKey
DOCUMENT_EVENTS_SERVICE_SECRET=$demoEventKey
DOCUMENT_INTERNAL_SERVICE_SECRET=$demoSourceKey
DOCUMENT_EVENT_READER_SECRET=$demoJournalKey
"@
[IO.File]::WriteAllText((Join-Path (Get-Location) '.env.fullstack-demo'), $demoConfiguration, [Text.UTF8Encoding]::new($false))
```

Compose dùng hostname container `db`, `core`, `document` ở mạng nội bộ; URL trong trình duyệt dùng các cổng host ở bảng trên. Không thay `http://document:8200` bên trong container bằng cổng host 8400. Không đặt key/credential trong biến `NEXT_PUBLIC_*`.

## 4. Build, migrate và chạy

```powershell
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Cau hinh Compose khong hop le.' }
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document up --build -d --wait
if ($LASTEXITCODE -ne 0) { throw 'Stack chua san sang; xem ps va logs.' }
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document ps -a
Invoke-RestMethod http://localhost:8300/health/ready
Invoke-RestMethod http://localhost:8400/health/ready
```

Core migrate trước khi khởi động; Document bootstrap tạo login/schema riêng rồi migrate trước API/worker. Các job bootstrap/migrate `Exited (0)` là bình thường; Core/Document phải healthy, hai worker phải running. Không chạy seed hoặc sửa schema thủ công để bỏ qua migration lỗi.

## 5. Tạo Admin và dữ liệu mẫu

Ứng dụng không tự tạo Admin khi boot. Chạy seed có guard trên đúng database demo:

```powershell
$demoPreviousSeedPassword = $env:CORE_SEED_ADMIN_PASSWORD
try {
    $env:CORE_SEED_ADMIN_PASSWORD = 'LumiDemoOnly!2026'
    docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document exec -T -e CORE_SEED_ADMIN_PASSWORD core python -m app.maintenance seed-dev --environment development --expected-database dev_lumi_fullstack_demo --school-id d4b55a29-6aae-4f9b-b6b1-d0e44ab2c990 --school-name 'Lumi Fullstack Local Demo'
    if ($LASTEXITCODE -ne 0) { throw 'Seed bi tu choi; khong xoa du lieu de ep seed.' }
} finally { $env:CORE_SEED_ADMIN_PASSWORD = $demoPreviousSeedPassword }
```

Admin demo: **`admin@seed.example.com` / `LumiDemoOnly!2026`**, chọn tab **Giáo viên & quản trị viên** tại http://localhost:3200/login. Đây là credential test công khai, chỉ dùng với database demo riêng, không dùng cho dữ liệu thật hoặc triển khai public. Không đổi Admin/mật khẩu trên môi trường dev 3000.

Seed lần đầu trả `created:true`; chạy lại cùng profile trả `created:false`, giữ mật khẩu/dữ liệu đã sửa. Có 1 Admin, 2 giáo viên đã phân công, 3 học sinh và 14 lớp Toán AUTO/MANUAL. Mật khẩu giáo viên/học sinh không được bàn giao; dùng quy trình kích hoạt/reset/mời hợp lệ bên dưới. Email `@seed.example.com` không phải hộp thư nhận thư thật.

## 6. Checklist trải nghiệm theo vai trò

Dùng profile trình duyệt riêng cho Admin, giáo viên, học sinh. Cookie `localhost` dùng chung giữa các cổng, nên không mở dev 3000 và demo 3200 trong cùng profile để so sánh phiên.

### Admin và học sinh — không cần SMTP

1. Admin mở `/admin/accounts`, `/admin/catalog`, `/admin/homerooms`, `/admin/classes`; xem roster `Seed 9A`, `Seed Math 9 AUTO/MANUAL` và giáo viên đã phân công.
2. Học sinh đã active `seed.student.1`: Admin mở tài khoản, xác nhận danh tính rồi cấp mã đặt lại mật khẩu. Trong profile khác mở `/reset-password`, dùng mã và tự đặt mật khẩu, sau đó đăng nhập tab **Học sinh** bằng username.
3. Kích hoạt lần đầu: Admin tạo học sinh ở `/admin/accounts/students/new`, lưu username/mã một lần. Người học vào `/activate`, nhập username/mã và đặt mật khẩu. Không có tự đăng ký hoặc mã tự tham gia lớp.
4. **Ai xếp lớp:** Admin quản lý roster lớp hành chính và ghi danh lớp môn học. Lớp MANUAL: Admin thêm học sinh vào danh sách thành viên. Lớp AUTO: Admin cập nhật roster rồi preview/sync theo phiên bản; giáo viên không tự nhập học sinh bằng join code.
5. Vào bảng tin cùng lớp: tạo/sửa/xóa bài hoặc bình luận của mình; thử hai profile để thấy đồng bộ và giữ bản nháp. Giáo viên còn có quản lý lịch; học sinh không được sửa bài của người khác hoặc mở Admin.
6. Tạo/import học sinh qua CSV UTF-8 với cột `username,display_name`, tối đa 100 dòng/2 MB; xem preview trước xác nhận. Xem audit và yêu cầu dữ liệu; chưa có executor tải/xóa dữ liệu liên service.

### Giáo viên — kích hoạt qua email

1. Cấu hình SMTP của bạn trong **file `.env.fullstack-demo` riêng**, theo phần Email delivery của [Core README](../services/core/README.md). Dùng `SMTP_HOST`, `SMTP_PORT`, `SMTP_FROM`, `SMTP_SECURITY`, `SMTP_USERNAME`, `SMTP_PASSWORD`. Gmail dùng mật khẩu ứng dụng, không đưa mật khẩu vào chat/Git. Không dùng email seed để nhận thư.
2. Áp dụng lại cấu hình Core, không đổi file hoặc project:

   ```powershell
   docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document up -d core
   ```

3. Admin mở `/admin/accounts/staff/invitations`, mời email thực nhận được thư. Người nhận bấm link email `/staff/invitation`, tự đặt mật khẩu; không dán token vào kích hoạt học sinh.
4. Admin phân công giáo viên mới vào lớp đang có học sinh. Giáo viên đăng nhập tab nhân sự, vào lớp phụ trách để thử bảng tin/lịch. Chỉ Admin có credential công khai; không tạo mật khẩu dùng chung hoặc lấy token từ DB để bỏ qua onboarding.

Chưa có SMTP thì vẫn thử Admin/Student; bộ integration test ở mục 8 kiểm tra giáo viên và email bằng SMTP TLS tổng hợp riêng, không gửi Gmail thật.

### Document — upload → chia sẻ → ghi chú → thu hồi

1. Giáo viên mở `/teacher/library`, tải tệp PDF/PPTX/DOCX/TXT/MD thật, tối đa 50 MiB theo chính sách server. Chờ **Sẵn sàng**; upload nhận thành công không có nghĩa đã xử lý xong.
2. Mở nguồn: sửa tên/mô tả, xem lịch sử, tải bản gốc, cấp quyền cho lớp ACTIVE đang phụ trách. Chỉ owner đổi/xóa tệp; PRIMARY/ASSISTING được gỡ nguồn khỏi lớp.
3. Học sinh mở **Tài liệu lớp** → Reader. PDF dùng Trang, PPTX dùng Slide, DOCX/TXT/MD dùng Mục. Chọn đoạn nguồn, bấm **Trích dẫn đoạn đã chọn**, thêm chữ tự viết, lưu ghi chú và đánh dấu vị trí.
4. Tải lại và mở **Ghi chú & Đã lưu**: dữ liệu còn, link mở đúng phiên bản/vị trí; thử cả màn hình điện thoại. Sửa/xóa ghi chú hoặc gỡ bookmark của mình.
5. Tải v2 hỏng cùng format: có lỗi v2 nhưng lớp tiếp tục đọc v1 đã sẵn sàng. Retry dùng lại tệp gốc, không tạo version mới.
6. Thu hồi chia sẻ khi Reader học sinh đang mở: API nguồn/tải file từ chối ngay ở request tiếp theo; UI đồng bộ và ẩn nguồn. Sổ tay giữ chữ tự viết, che quote và không cho sửa note gắn nguồn đã mất quyền.
7. Thử lưu trữ lớp: đọc nguồn/sửa ghi chú còn quyền được giữ, thêm/gỡ chia sẻ bị chặn. Xóa nguồn đang dùng cần xác nhận số lớp/revision; 409 yêu cầu xem lại dữ liệu mới.
8. Xem chuông/trang thông báo sau chia sẻ/đổi nguồn. Cần cả `document-worker` và `notification-worker`. Mở thông báo vẫn kiểm tra lại quyền; notification không cấp quyền nguồn.
9. Thử Offline/lost response trên dữ liệu test: dùng nút đối soát, không tự tạo một upload hoặc note thứ hai. Hộp sửa ghi chú có nút đối soát ngay trong dialog.

AI Tutor/index/RAG chưa có trong TASK-017; READY chỉ chứng nhận trích xuất. PDF scan cần OCR bên ngoài. Không có API lịch sử/resend/revoke invitation, lịch sử import hay executor dữ liệu chưa đặc tả; không coi preview là tính năng live.

## 7. Chạy Web native để sửa code

Giữ backend của demo ở trên, dừng riêng container Web để giải phóng cổng 3200:

```powershell
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document stop web
Set-Location apps/web
npm.cmd ci
if (Test-Path .env.local) { throw 'Da co .env.local; giu file cu va sua cau hinh thu cong, khong ghi de.' }
Copy-Item .env.example .env.local
```

Tạo `apps/web/.env.local` từ mẫu, đặt `CORE_API_URL=http://localhost:8300`, `DOCUMENT_API_URL=http://localhost:8400`, `WEB_ORIGIN=http://localhost:3200`, `NEXT_PUBLIC_DATA_MODE=live`. `CORE_PROXY_SECRET` phải khớp giá trị riêng trong `.env.fullstack-demo`; sao chép trên máy, không đưa vào chat/Git. Sau đó:

```powershell
npm.cmd run dev -- --hostname 127.0.0.1 --port 3200
# Production: dung dev server truoc, npm.cmd run build, roi:
# npm.cmd start -- --hostname 127.0.0.1 --port 3200
```

Chạy `server.mjs` qua npm scripts; không gọi trực tiếp `next dev/start` vì thiếu listener attestation. Dừng server trước khi build vào `.next` đang phục vụ. Preview `npm run dev:mock` chỉ là mock rõ ràng, không xác nhận backend. Đã có môi trường Core trên 3000/8000 thì dùng [Document README](../services/document/README.md) để bổ sung service mà không tạo demo này.

## 8. Kiểm thử và chẩn đoán

```powershell
# Tai root; fixture PostgreSQL/volume rieng, khong dung DB dang hoat dong:
python services/document/scripts/test-service.py --full-core
Set-Location apps/web
npm.cmd ci
npm.cmd run check
$env:CORE_DOCUMENT_TEST = '1'
$env:CORE_BROWSER_EXECUTABLE = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
try { npm.cmd run test:core } finally {
    Remove-Item Env:\CORE_DOCUMENT_TEST -ErrorAction SilentlyContinue
    Remove-Item Env:\CORE_BROWSER_EXECUTABLE -ErrorAction SilentlyContinue
}
```

Đổi đường dẫn Chrome theo máy; bỏ biến Chrome nếu chỉ kiểm tra HTTP/render. Runner build live, tạo tài khoản/tệp/SMTP TLS/profile tổng hợp riêng rồi dọn đúng fixture; không dùng Admin demo, Gmail hoặc DB đang hoạt động. Ghi rõ lệnh và kết quả thực, không suy từ test chức năng ra KPI tải. [Bằng chứng TASK-017](../apps/web/docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md): 25 Document, 428 Core, 346 Web tests; 28 nhóm HTTP và 13 nhóm Chrome đã đạt.

| Hiện tượng | Kiểm tra |
|---|---|
| Không đăng nhập được sau clone | Đúng cổng/project, seed đã chạy, đúng tab nhân sự/Student; clone không chứa DB từ máy khác |
| 401 khi giờ máy lệch | Đồng bộ giờ Windows/WSL rồi đăng nhập lại; không tắt xác minh JWT |
| Proxy 403 / không kết nối | Dùng npm server scripts, `WEB_ORIGIN` đúng scheme/host/port, key proxy khớp Core; không thay `localhost` bằng `127.0.0.1` trên thanh địa chỉ tùy ý |
| Lời mời/token lỗi | Đúng email/link mới nhất và origin; không dùng staff token cho `/activate`; kiểm tra SMTP trước khi gửi lại |
| Upload pending / không thông báo | Kiểm tra hai worker và service keys, không chỉ Web; READY không có nghĩa AI đã index |
| 403 nguồn / 409 revision | Xem quyền lớp/grant hiện hành hoặc tải lại snapshot, không tự nâng quyền hay replay mù |
| Port bị chiếm | Dừng đúng tiến trình của mình hoặc chọn cổng khác, sửa đồng bộ origin/CORS/URL; không reset DB |

```powershell
# Tu root:
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document logs --tail 60 core document document-worker notification-worker
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document down
# Lan sau, giu nguyen file env/volume:
docker compose --project-name lumi-fullstack-demo --env-file .env.fullstack-demo --profile document up -d --wait
```

Không thêm `--volumes` nếu cần giữ tài khoản/tài liệu. Backup phải có DB và volume `document-files`. Không commit `.env*` riêng, SMTP credential, mã kích hoạt/reset, private login file, tệp upload hay log chứa dữ liệu thật. Repo chỉ mang mẫu cấu hình, code/migration/test và tài khoản Admin demo công khai đã nêu.
