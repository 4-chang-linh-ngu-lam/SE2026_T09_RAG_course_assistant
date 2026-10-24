# Bảng tin lớp và thông báo — 23/10/2026

Yêu cầu: sửa tính dễ dùng và đồng bộ bảng tin/bình luận/thông báo ở cả Web và Core. Giữ 63 operation hiện có; chưa mở công việc tối ưu hiệu năng hay service khác.

## Phần logic đã triển khai

- Controller bảng tin theo actor/lớp: GET một lượt tại một thời điểm, vô hiệu hóa GET cũ trước mutation, chỉ áp dụng ACK đã xác nhận. Mất quyền xóa projection cũ; lỗi đọc khóa thao tác ghi tới khi đọc lại thành công. Unknown không tự replay hoặc tự đối soát bằng polling.
- Adapter giữ updated_at của bình luận, phân biệt tác giả chưa có display_name bằng phần đầu UUID công khai, không suy diễn role/email. Bỏ bài đã bị xóa giữa lần đọc danh sách và lần đọc bình luận; lỗi khác vẫn từ chối toàn snapshot.
- Provider thông báo dùng chung theo phiên; tải khi tab hiện/online, focus hoặc mỗi 10 giây. Không dùng localStorage/sessionStorage. Đổi actor/role/school hủy đọc cũ. Unknown cần đối soát rõ ràng; GET trước mutation không ghi đè ACK.
- Deep link chỉ dựng từ type/UUID và route đã có. Student chuyển lớp mở lớp đích. Admin metadata không được cấp link Social/Calendar.
- Worker kiểm tra bài và bình luận còn tồn tại, đúng tác giả; nội dung đã xóa không phát thành thông báo mới. Audience, retry, dedup và read-all watermark giữ nguyên.

## Trạng thái nghiệm thu

UI mới đã được Codex hoàn thiện tại máy theo yêu cầu tiếp tục của người dùng; không chạy AGY hoặc gửi mã ra dịch vụ AI bên ngoài. Bảng tin dùng view được điều khiển bằng controller riêng; bỏ CSS bảng tin cũ trong globals để tránh xung đột. Bài viết có tác giả/ngày sửa, tìm trong nội dung đã tải, xem thêm bài viết, thu gọn chuỗi bình luận, textarea xuống dòng và Ctrl+Enter gửi (không gửi khi IME đang composition). Mọi mutation khóa khi busy/unknown/read-only; sửa/xóa có dialog. Deep link đưa focus tới bài/bình luận và báo rõ khi nội dung không còn khả dụng. Chuông dùng cùng inbox với trung tâm thông báo; không hiển thị số 0 giả khi chưa tải được.

Nghiệm thu production live đạt: **22 nhóm HTTP và 7 nhóm Chrome**, gồm hai actor tạo/sửa/xóa bài/bình luận không reload, giữ bản nháp, mở và focus đúng bình luận từ thông báo, đồng bộ số chưa đọc ở chuông, và link tới nội dung đã xóa. Kiểm tra ở 1440px/390px; không có uncaught exception. Ảnh desktop/mobile đã được xem lại trực tiếp. Fixture là database/SMTP TLS/tài khoản tổng hợp riêng, không gửi email thật.

Bằng chứng đã chạy: `npm run check` (boundary + TypeScript + **338 test**, không skip), `pytest tests/notification/test_social_delivery.py -q -W error -p no:cacheprovider` trong Python Linux runtime (**9 passed**, không skip), Ruff check/format và `git diff --check` đạt. Không cài thêm dependency; pytest dùng các package công cụ đã có trên máy, mount chỉ đọc. `CORE_BROWSER_EXECUTABLE=<Chrome> npm run test:core` exit 0; production live build/boundary/release scan, migration check, seed repeat và DB outage/recovery đều đạt. Artefact tổng hợp: `lumi-core-smoke-44mpvz`; xem [evidence JSON](evidence/core-class-feed-notifications-2026-10-23.json).

HTTP contract, schema và migration không đổi. Full backend pytest suite không chạy lại; số 9 là nhóm regression mới, không phải toàn bộ Core. Build có các cảnh báo CSS autoprefixer sẵn có ở Assessment/Tutor ngoài phạm vi này. Tự đồng bộ dùng GET mỗi 10 giây khi tab hiện và có mạng, thêm focus/online/manual refresh; không thêm WebSocket/SSE. Unknown mutation chỉ mở khóa sau GET đối soát rõ ràng, không tự replay. Đây là hoàn thiện chức năng kết nối; tối ưu tải dữ liệu vẫn được hoãn theo yêu cầu.

Đã áp dụng đúng image đã nghiệm thu vào Core/worker chính và Core/worker/Web demo; Web chính build live lại trên Windows và khởi động lại. `localhost:3000/login`, `localhost:3100/login`, Core ready `8000/8100` trả 200; Admin API anonymous qua Web chính trả 401. Hai container database giữ nguyên ID; SMTP chính vẫn cấu hình và origin 3000, demo giữ origin 3100. Fixture đã dọn container/volume, tệp credential và profile browser; worktree AGY chưa dùng cũng đã dọn. Chưa commit/push.

Owner review khi tạo PR: Web session/navigation, Core.Social và Core.Notification. Không có thay đổi schema/migration/HTTP endpoint hay quyền backend.
