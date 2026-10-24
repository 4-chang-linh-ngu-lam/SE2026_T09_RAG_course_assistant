# Tiếp tục hoàn thiện fullstack — 22/10/2026

**Cập nhật sau báo cáo:** người dùng đã duyệt 38 API hiện có; allowlist hiện là 55 operation. Kết quả mới tại [báo cáo tích hợp đã duyệt](CORE_APPROVED_INTEGRATION_2026-10-22.md). Các số liệu/đề xuất chưa duyệt bên dưới mô tả thời điểm trước quyết định này, được giữ để truy vết; không phải trạng thái hiện tại.

Yêu cầu: tiếp tục hoàn thiện fullstack sau đợt [full verification](FULL_VERIFICATION_2026-10-22.md). Working tree `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` cộng các thay đổi chưa commit có sẵn. Codex thực hiện integration/tooling theo skill `lumi-frontend-orchestrator`; không tạo layout mới, không gọi AGY hoặc thay model/provider.

## Đã triển khai

- Thêm `scripts/test-core-integration.mjs` và lệnh **`npm.cmd run test:core`** trong `apps/web`. Đây là một lần chạy HTTP/DB thật, không dùng mock hoặc URL/dữ liệu vận hành.
- Runner tự cấp port loopback khác nhau, Compose project và Core image tag riêng, PostgreSQL volume mới, JWT/internal/proxy key và mật khẩu tổng hợp riêng. Không dùng lại image tag, database hoặc tiến trình dev; SMTP không được kế thừa vào child environment.
- Build production Web/Core/worker, kiểm tra runtime không phải root, app cài từ wheel và Alembic drift; guarded seed rồi seed lặp an toàn; chạy **7 Notifications + 8 Identity/security HTTP groups**. Kiểm tra DB outage ready503/live200 và recovery ready200.
- Cleanup trong finally; lỗi chỉ in phase/type, không in chi tiết assertion có thể chứa credential. File env chứa credential được xóa; chỉ giữ log riêng và summary tổng hợp ngoài repo. Nguồn môi trường của terminal không bị sửa.
- Bổ sung hướng dẫn vào [README](../README.md). Không mở API mới, không đổi Business Rules/schema/permission/migration.

## Kiểm chứng thực chạy

| Kiểm tra | Kết quả |
|---|---|
| Baseline `npm.cmd run check` | Exit **0**, **266/266**, 0 fail/skip/cancelled; TypeScript/boundaries đạt |
| `node --check scripts/test-core-integration.mjs` | Exit **0** |
| `npm.cmd run test:core` | Exit **0**; production build/ready, non-root package, migration, seed repeat, **15/15 HTTP groups**, DB outage/recovery và cleanup đạt |
| Nhánh thất bại của runner | Thử chủ động báo build-failure sau khi thật sự tạo **DB container + volume riêng**; runner trả **1**, chạy cleanup và xóa file credential. Inspect xác nhận không còn container/volume của project đó |
| Windows preload của phép thử lỗi | Lần thử đầu sai định dạng đường dẫn `--import` nên chưa chạy runner; đã sửa thành file URL rồi kiểm chứng lại đúng nhánh lỗi có tạo/xóa DB thật. Không coi lỗi loader ban đầu là bằng chứng cleanup |

Lần chạy thành công dùng `lumi-smoke-b2a6735e8988`; log riêng ở thư mục tạm được runner in ra. Bằng chứng tổng hợp được lưu cùng báo cáo. Production build ở đây chạy trong Docker; không ghi đè `.next` của Web dev đang mở.

[Bằng chứng tổng hợp](evidence/fullstack-followup-2026-10-22.json) ghi riêng kết quả thành công, nhánh cleanup khi thất bại và các probe không phải acceptance. Fixture hiệu năng riêng cũng đã xóa DB/container/anonymous volume/network và file credential. Sau dọn, Core/DB dev healthy, worker running, Core ready và Web `/login` 200; W32Time Running/timesyncd active. `git diff --check` đạt.

## Chẩn đoán hiệu năng — vẫn còn mở

Không đổi workload/gate/application để làm đẹp kết quả. Benchmark 600 giây cũ được giữ nguyên, gồm client p95 27,2 giây và bảy transport/contract error. Các phép thử sau chỉ là **chẩn đoán ngắn**, không được tính là Core-06 acceptance:

| Probe | Kết quả |
|---|---|
| 100 client pool riêng, warmup 5s / đo 20s | 633 request, client p95 **3.564 ms**, backend p95 **368 ms**, success 100%, event-loop lag p95 **1.794 ms**; chưa hết nghẽn client |
| Sample call stack client, đo 20s | Phần lớn sample ở importlib filesystem lookup; cũng thấy quét socket/connection pool. Chỉ ghi tên hàm/dòng, không locals/token |
| Thử thêm sniffio vào dependency tạm, warmup 5s / đo 20s | 1.008 request, client p95 **5.087 ms**, backend p95 **179 ms**, success 100%. Trước đó môi trường thiếu sniffio, HTTPcore lặp import dự phòng; 300 lần fallback mất khoảng 0,44s. Khi đã có sniffio, probe import không còn lookup trong pha đo; latency vẫn cao |
| Đổi tạm sang HTTPX2 đã có trong dev dependencies, warmup 5s / đo 20s | 1.254 request, client p95 **1.535 ms**, backend p95 **596 ms**; script trả **1** vì backend vượt ngưỡng 500 ms. Không chọn phép thử này làm kết quả đạt, không đổi mặc định runner hoặc dependency project |

Những probe khác thời điểm/warmup/client nên không phải A/B có cách ly tài nguyên. Runner hiện đặt Uvicorn và load generator ở hai thread cùng Python process, chung GIL; cần đo tách process và trace hàng đợi trước khi quy nguồn độ trễ hoặc kết luận hiệu năng đầu cuối đã đạt. Thư viện thử nghiệm chỉ cài ngoài repository, không thay dependency ứng dụng.

## Phần nối live cần chốt tiếp

[Đề xuất 38 API Core hiện có](CORE_REMAINING_CONTRACT_REVIEW_2026-10-22.md) đã cụ thể hóa Classroom/Social/Calendar/Administration/import: giữ wire/permission thật, không thêm endpoint hoặc mô phỏng field thiếu. Câu hỏi chốt phạm vi đã gửi; **chưa có quyết định mới**, nên allowlist vẫn 17 operation đã duyệt.

Lý do cần chốt: [apps/web/AGENTS.md](../AGENTS.md) yêu cầu “Contract approval is required before extending service proxy/decoders.” [Skill repository](../../../.agents/skills/lumi-frontend-orchestrator/SKILL.md) yêu cầu “Do not turn `pending-contract` into live calls or invent API/schema/policies.” Core API_CONTRACT vẫn ghi các nhóm trên PROPOSED. Quyền sửa lỗi/tooling đã giao không bị yêu cầu cấp lại.

Sau khi chốt, thứ tự triển khai là transport/decoder theo operation → live adapter/DTO mapping → workspace tương ứng → HTTP/DB verification → readiness. Các phần còn thiếu read API như catalog/teacher assignments/accounts/homeroom sẽ có đề xuất schema/quyền cụ thể riêng; không tự giả teacher role, class revision hoặc mutation atomic để khớp preview UI.

Document/AI/Learning/Learner Intelligence hiện mới có ranh giới kiến trúc, chưa có thiết kế API chi tiết để triển khai fullstack. Browser UI/SMTP thật chưa được chứng nhận. Chưa commit, push, tạo PR hoặc deploy; không gọi phần này là fullstack hoàn chỉnh.
