# Core/Web runtime follow-up — 23/10/2026

Phạm vi tiếp nối: sửa hạ tầng request, khắc phục phương pháp tạo tải trên Windows/Docker, hoàn thiện hai trạng thái quản trị và CI. Nhánh `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` cùng worktree chưa commit có sẵn. Không thêm API, schema, Business Rule hoặc migration; Web vẫn mở 63 operation và Core có 67 operation. Báo cáo trước giữ nguyên giá trị lịch sử tại [Core completion](CORE_COMPLETION_2026-10-23.md).

**Kết luận mới nhất: các gate chức năng bên dưới đạt; Core-06 chưa đạt vì p95 backend vượt500ms trên host local. Chưa chốt hoàn thành toàn bộ Core/G2.**

## Thay đổi

- `Common.errors`: correlation middleware dùng ASGI trực tiếp, giữ UUID hợp lệ hoặc tạo UUID mới; response/error vẫn có cùng `X-Correlation-ID`. Không tạo task/stream trung gian cho từng request. Test bao phủ headers, lỗi đã che chi tiết, streaming, cancellation/cleanup và scope không phải HTTP. Chưa dùng thay đổi cấu trúc này làm bằng chứng hiệu năng.
- `Core.bootstrap`, `Common.pagination`, `Classroom.router`: các dependency chỉ tạo callable/service hoặc kiểm tra pagination chạy trực tiếp trên event loop. SQL, auth snapshot và endpoint đồng bộ vẫn ở worker; auth vẫn đọc trạng thái/role/session_version hiện hành và trả connection trước endpoint. Factory Identity public giữ nguyên chữ ký/DTO.
- Web quản trị: nhận diện homeroom UUID không phân biệt hoa/thường như contract; lớp chưa liên kết homeroom hiển thị điều kiện thiếu và chặn AUTO preview tại UI/controller, không gửi request biết trước sẽ bị từ chối. Ghi danh MANUAL vẫn dùng API hiện có.
- Runner tải có image Linux riêng, đọc dependencies từ `pyproject.toml`; source/thư viện nằm trong image. [Lệnh PowerShell](../../../services/core/tests/performance/run-class-list-load.ps1) tạo PostgreSQL16/network riêng với credential ngẫu nhiên, không đọc `.env` ứng dụng, lưu JSON mới rồi dọn tài nguyên chính xác của lần chạy. Không ghi đè evidence đã tồn tại. Chạy được cả từ CMD qua `powershell.exe` và PowerShell.
- Báo cáo tải thêm phiên bản package, hash source ứng dụng thực sự được import, runtime, độ trễ event loop client/server và nhãn lỗi giao thức hữu hạn. Không ghi URL, header, token hoặc chuỗi exception nguyên văn. Không retry để che lỗi; không đổi ngưỡng 500ms/99%/0 sai scope.
- CI thực sự xuất `rule-evidence.json` từ JUnit và có `workflow_dispatch` với `run_core_load=true` cho bài 600 giây/100 user. File workflow tồn tại không chứng minh GitHub đã chạy; chưa push hay chạy CI từ xa.

## Vì sao sửa phương pháp tải

Ở lần đo cũ, client p95 3,83 giây cùng 53 `RemoteProtocolError` chưa được giải thích. Chẩn đoán mới trên fixture riêng cho thấy event loop client có p95 khoảng 1,99 giây, max 2,82 giây; lỗi thuộc nhãn đóng kết nối trước headers. CPU profile ghi khoảng 25,84 giây trong `posix.stat`, và 24,35 giây ở đường dò thư viện async của HTTP Core. Source thư viện đang cài có nhánh dò optional import lặp lại; cache công cụ được bind từ ổ Windows. Đây là bằng chứng về chi phí tạo tải, không phải bằng chứng API mất quyền hoặc DB mất dữ liệu.

Giữ nguyên code/HTTPX/workload, chuyển source và thư viện vào Linux làm client event-loop p95 còn khoảng 4,29ms và không có lỗi giao thức trong lần so sánh 35 giây. Backend nhận được nhiều request hơn, làm lộ độ trễ backend chưa đạt ngưỡng ở các lần đo ngắn. Vì vậy **không lấy số 477ms lịch sử để chứng nhận baseline hiện tại**, và không so trực tiếp throughput của hai cách tạo tải như một cải thiện backend.

Các thử nghiệm private thay app-scoped auth factory, giảm admission xuống bốn request hoặc đổi nhịp GIL xuống1ms/0,1ms không đạt ngưỡng; không áp dụng chúng. Profile ghi nhận chi phí dựng lại dependency graph và chờ luồng/DB, nhưng chưa chứng minh một thay đổi đủ giải quyết p95. Giữ một Uvicorn worker vì limiter/idempotency hiện còn process-local; không tăng worker để lấy số tải đẹp hơn.

## Kiểm chứng hiện tại

| Kiểm tra thực sự chạy | Kết quả |
|---|---|
| Common, middleware, admission, runner; warnings-as-errors | 53 passed, 0 skip/failure |
| OpenAPI/contracts, module boundaries, Identity public, pool1/current-role/revocation | 62 passed, 0 skip/failure; cùng nhóm trên là115 case ID phân biệt |
| `npm.cmd run check`: boundaries, TypeScript, tests | 317 passed, 0 skip/failure |
| Ruff lint + format trên bản sao Linux | Passed; 141 Python files already formatted |
| Production Core/Web/PostgreSQL/worker HTTP | 22 nhóm passed: 7 Core/46 operation, 7 Notifications, 8 Identity/security |
| Production live Web build/release scan, runtime non-root/wheel, migration/seed repeat | Passed trong fixture HTTP |
| DB outage/recovery | ready503/live200, sau phục hồi ready200 |
| SMTP | Sender Core + TLS sink tổng hợp passed; chưa gửi email ngoài |
| Browser | Công cụ trả inventory rỗng; HTTP/SSR không chứng nhận click/hydration |
| CI YAML cục bộ | Parse passed, không khóa trùng, quyền chỉ đọc, tải manual mặc định tắt; chưa chạy GitHub |
| Runner PowerShell | Parse0 lỗi; thử output đã tồn tại bị từ chối, SHA256 evidence giữ nguyên |

[Bằng chứng tổng hợp](evidence/core-runtime-followup-2026-10-23.json). Không cộng các ca hồi quy chồng lặp vào 387 ca backend lịch sử để tạo tổng test mới.

## Kết quả tải đủ thời lượng

[Raw aggregate JSON](../../../services/core/test-evidence/core-runtime-2026-10-23/core-load.json): warmup30s,100 user,600s cấu hình/601,977s thực đo,10 lớp ×50 học sinh, interval1s, một worker và pool15 như profile trước. Source/dependencies nằm trong image Linux; máy phát và server khác process/GIL. Host dùng chung, không đặt CPU/RAM reservation; đây là Core class-list subset, không phải toàn TP-01.

| Chỉ số | Thực đo |
|---|---|
| Request | 34.757 |
| HTTP200 / HTTP503 | 34.756 /1 |
| Lỗi transport/protocol | 0 |
| Thành công | 99,9971% |
| Sai scope | 0 |
| Backend p95 | **2.430,05ms — chưa đạt500ms** |
| Client p95 | 2.402,91ms |
| Event-loop p95 client / server | 3,98ms /20,50ms |
| `passed_core_thresholds` / CLI exit | `false` /1 |

Lỗi giao thức quan sát trước đã hết trong lần tải dài này, nhưng độ trễ backend vẫn là việc chưa hoàn tất. Cần đo tiếp các pha SQL/thread/queue trên môi trường ghi rõ tài nguyên và xác minh cải thiện với cùng100 user/600s; không đổi pacing hay bỏ503 để chuyển gate thành xanh. Nếu đề xuất nhiều worker, phải giải quyết và kiểm thử limiter/idempotency dùng chung trước.

## Runtime local sau cập nhật

Core và notification-worker đã được rebuild/restart; không seed hay xóa volume ứng dụng. Core ready200, Web `/login`200, proxy `/api/v1/admin/users` không credential trả401; OpenAPI67 operation. Runtime UID10001, import từ installed package, hash app khớp source của bài tải dài. Chênh Windows so với HTTP Date Core khoảng0,709s (Date có độ phân giải1s), không thay đổi giờ hệ thống trong lượt này.

Main Core chưa cấu hình SMTP host/from; phần email ngoài vẫn chưa triển khai vận hành. Còn cần phiên trình duyệt để kiểm tra click/hydration. Document/AI/Learning/Intelligence tiếp tục pending-contract; chưa tạo endpoint hoặc giả dữ liệu để vượt gate G2.

## Chạy lại từ root repository

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File services/core/tests/performance/run-class-list-load.ps1
```

Mặc định: 100 user độc lập, 10 lớp × 50 học sinh tổng hợp, warmup30s, đo600s, interval1s như baseline trước. JSON ghi rõ closed-loop và client/server p95. `-DurationSeconds 30 -WarmupSeconds 5` chỉ là chẩn đoán; không phải nghiệm thu Core-06. Khi lỗi, log riêng ở thư mục Temp của lần chạy; cleanup không đụng `pgdata` hay container của ứng dụng.

Owners cần review khi gom PR: Core.Common/Identity, Classroom, Web integration và CI. Codex thực hiện logic/hạ tầng/kiểm thử; không gọi thêm AGY hoặc gửi mã nguồn tới dịch vụ AI ngoài trong lượt này. Không commit/push/merge/deploy.
