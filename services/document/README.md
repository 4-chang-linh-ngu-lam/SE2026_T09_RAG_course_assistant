# Document Service — TASK-017

Service độc lập quản lý tệp gốc, phiên bản, trích xuất văn bản, chia sẻ theo lớp, ghi chú và bookmark riêng. Hợp đồng đã được người dùng duyệt ngày 2026-10-23: [thiết kế](../../docs/architect/microservices-v1/document/DESIGN.md), [27 public API](../../docs/architect/microservices-v1/document/API_CONTRACT.md), [events](../../docs/architect/microservices-v1/document/EVENT_CONTRACT.md).

Python 3.12/FastAPI, PostgreSQL schema `document` với login riêng, volume tệp riêng và worker DB lease. Không truy vấn bảng Core. Mỗi request xác minh actor và quyền hiện hành qua Core; Admin không tự có quyền đọc thư viện giáo viên. Mọi file đều tải qua API kiểm tra quyền, không có URL công khai.

Máy mới clone repo: dùng [hướng dẫn fullstack](../../docs/LOCAL_DEVELOPMENT.md) để dựng Core–Document–Web và seed Admin trong một database demo riêng. Phần dưới dành cho môi trường Core đã cấu hình.

## Khởi động cùng môi trường Core hiện có

Cần Docker Desktop Linux containers, cấu hình Core `.env` và Web live đã hoạt động. Từ repository root chạy PowerShell:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File services/document/scripts/configure-local.ps1 -Start
docker compose --profile document ps -a
Invoke-RestMethod http://localhost:8200/health/ready
```

Script giữ cấu hình Core/SMTP đang có, tạo DB credential và ba service key ngẫu nhiên, riêng biệt trong `.env` bị Git bỏ qua; thêm `DOCUMENT_API_URL` vào `apps/web/.env.local`. Không in secret. Không reset database/tài khoản/lớp. `document-bootstrap` chỉ dùng credential quản trị khi tạo login/schema; API và worker dùng login Document không có quyền schema Core. Alembic chạy riêng trước API/worker, không tự chạy migration ở mỗi worker.

Web chạy native cần khởi động lại sau đổi môi trường. Dừng tiến trình Web trước khi build vào `.next` đang phục vụ, rồi từ `apps/web`:

```powershell
npm run build
npm start
```

Nếu Web chạy bằng Compose, cấu hình server đã trỏ `http://document:8200`; dùng `docker compose --profile document up -d --build web` khi cổng Web không bị native server chiếm. Namespace browser là `/api/document/v1`, không cho browser gọi internal API hoặc nhận service key.

## Luồng trải nghiệm

1. Admin dùng luồng Core sẵn có để tạo môn/lớp, gán giáo viên PRIMARY/ASSISTING và thêm học sinh. Không có tự đăng ký hay mã tham gia lớp.
2. Giáo viên đăng nhập → **Thư viện tài liệu** (`/teacher/library`) → tải PDF/PPTX/DOCX/TXT/MD thật, tối đa 50 MiB theo chính sách server. Upload thành công tạo job; chờ trạng thái **Sẵn sàng** rồi mở nguồn.
3. Trong chi tiết nguồn: sửa tên/mô tả, tải bản gốc, xem lịch sử, tải phiên bản mới và cấp quyền cho lớp đang phụ trách. Lớp lưu trữ không được thêm/gỡ nguồn. Đồng giảng viên được gỡ nguồn khỏi lớp, chỉ owner được đổi/xóa file nguồn.
4. Học sinh lớp đó → **Tài liệu** → mở Reader. PDF dùng Trang, PPTX dùng Slide, DOCX/TXT/MD dùng Mục. Reader hiển thị văn bản đã trích xuất; tải bản gốc để xem định dạng gốc.
5. Chọn đoạn văn bản → **Trích dẫn đoạn đã chọn** → nhập chữ tự viết → lưu ghi chú; đánh dấu từng vị trí. Mở **Ghi chú cá nhân** (`/student/notes`) để sửa/xóa và mở đúng phiên bản.
6. Giáo viên tải v2 hỏng: v2 hiện lỗi, lớp tiếp tục đọc v1 đã xử lý thành công. Retry dùng lại tệp gốc, không tạo phiên bản mới.
7. Giáo viên thu hồi chia sẻ: request đọc/tải nguồn tiếp theo trả 403, Reader đang mở xóa nguồn khi đồng bộ. Ghi chú cá nhân giữ chữ tự viết và nhãn lịch sử; quote bị che và không cho sửa ghi chú gắn nguồn đã mất quyền. Chủ ghi chú vẫn được xóa ghi chú/bookmark.
8. Xóa nguồn yêu cầu xác nhận số lớp đang chia sẻ và revision hiện hành. Grant thay đổi trong lúc xác nhận trả 409. Nguồn bị xóa mềm; không tự áp đặt lịch xóa tệp/lịch sử.
9. Mất phản hồi upload: giữ trạng thái chưa xác định, dùng **Đối soát upload đã gửi**. Nếu cần gửi lại, nút riêng phát đúng yêu cầu/key/file đã giữ; không tạo yêu cầu mới tự động. 404 receipt chưa chứng minh request trước thất bại.

Thông báo thay đổi nguồn đi qua outbox Document → Core.Notification và kiểm tra lại quyền hiện hành khi phát. Email thật không phải điều kiện để thử Document. AI indexing/tutor thuộc TASK-018; READY chỉ chứng nhận trích xuất, không chứng nhận RAG. PDF ảnh quét cần OCR bên ngoài; PDF mã hóa hoặc không có text hiển thị lỗi rõ.

## Kiểm thử có thể chạy lại

Dùng `--core` cho nhóm regression Identity/Notification ngắn hơn, `--full-core` để chạy toàn bộ Core. Không dùng database hoạt động để chạy pytest. Runner tạo PostgreSQL/schema/volume ngẫu nhiên riêng, kiểm tra migration drift và xóa đúng fixture của nó:

```powershell
python services/document/scripts/test-service.py --full-core
cd apps/web
npm run check
$env:CORE_DOCUMENT_TEST='1'
$env:CORE_BROWSER_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'
npm run test:core
```

Runner HTTP build production Core/Web/Document/worker, tạo tài khoản và tệp tổng hợp, dùng SMTP TLS giả lập, không gọi Gmail thật. Chrome dùng profile tạm riêng. Logs chứa fixture riêng nằm trong thư mục TEMP và không đưa vào Git. Xem [báo cáo nghiệm thu](../../apps/web/docs/DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md) để biết kết quả thực tế và giới hạn.

## Vận hành

`docker compose --profile document logs --tail 80 document document-worker` để kiểm tra tiến trình. `/health/live` chỉ kiểm tra API sống; `/health/ready` kiểm tra DB, volume và Core. Mất Core thì fail closed. Backup phải đi cùng database và volume `document-files`; không chạy `down --volumes` trên môi trường cần giữ dữ liệu. Không sửa migration đã áp dụng. Worker hết lease có thể được claim lại; generation cũ không được công bố kết quả.

Không có purge/retention tự động, HA, OCR hoặc SLA hiệu năng được chứng nhận trong task này. Owner Document/Core.Classroom/Core.Notification/AI cần review hợp đồng và phần liên quan khi tạo PR.
