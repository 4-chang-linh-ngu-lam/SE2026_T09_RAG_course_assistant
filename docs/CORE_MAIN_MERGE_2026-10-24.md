# Đồng bộ main vào core_full — 24/10/2026

## Phạm vi

- Nhánh nguồn: `core_full`, trước đồng bộ là `7858e878d75031eed519c76dd7f13b48fed4676d`.
- Nhánh bàn giao bản sửa được người dùng chọn: `fix/12-core-full-main-conflicts`. Không cập nhật trực tiếp `core_full`; PR #26 vẫn dùng head cũ cho đến khi bản sửa được tích hợp vào nhánh đó.
- Nhánh đích được tích hợp: `main` tại `d7ee28d`; mốc chung là `c54a55e`.
- PR liên quan: [#26](https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant/pull/26).
- Merge thực hiện trên worktree riêng, không sửa Business Rules, không push main hoặc merge PR. Không rebase/force-push lịch sử nhánh chia sẻ.

## Quyết định giải quyết conflict

Git báo 28 file conflict, chủ yếu do cùng module được thêm trên cả hai nhánh. Đã đối chiếu nội dung hai phía trước khi ghép; không dùng chiến lược bỏ toàn bộ thay đổi của một nhánh.

| Nhóm | Kết quả |
|---|---|
| Classroom / Administration / Identity | Giữ các API và kiểm tra quyền hiện hành của nhóm, cùng tám GET metadata đã duyệt cho frontend; giữ khóa roster FOR SHARE và Session xác thực ngắn |
| Social / Notification / Document | Giữ snapshot V2, kiểm tra bài/bình luận đã xóa, internal Document intake và receipt; không trả lại nội dung hoặc credential vào notification |
| Migration | Giữ nguyên mọi revision đã áp dụng ở cả hai nhánh; head Core `0013`, Document `document_0003`; giữ guard khi bảng receipt có dữ liệu |
| CI | Kết hợp migration heads/maintenance report và rule evidence từ main với `npm ci`, Web check/build, live proxy origin/key và bước Compose của core_full; giữ CI cho tv4 và thêm core_full |
| Compose / env mẫu | Giữ topology Core–Document/Web, worker và service keys; bổ sung ba tùy chọn DB pool từ main; không đưa cấu hình riêng vào Git |
| Tài liệu | Giữ bàn giao TV4 và task status từ main, giữ hướng dẫn demo/source layout của core_full; bổ sung chi tiết access/admission/import/notification và ghi rõ V1 không được worker phát |

Mã Python, test, migration và mã Web sau giải quyết conflict giống bản `7858e87`; phần kết hợp mới là cấu hình triển khai/CI và tài liệu. Điều này được kiểm tra bằng diff, không suy ra từ tên file hoặc ngày commit.

Image kiểm thử Core bổ sung `pytest-cov` theo cùng giới hạn phiên bản trong `pyproject.toml` để chạy coverage gate của CI trong fixture Docker, đặt file coverage ở `/tmp` cho user không phải root. Image runtime không thêm dependency kiểm thử.

## Kiểm chứng

| Kiểm tra thực chạy trên bản ghép | Kết quả |
|---|---|
| `python -m ruff check` và `ruff format --check` trên Core/Document, migrations và tests | Đạt; 172 file Python đúng format |
| Workflow YAML không trùng khóa/job; Compose profile Document `config --quiet` | Đạt; giữ quyền workflow `contents: read` và bốn job hiện có |
| `npm.cmd ci --no-audit --no-fund`, `npm.cmd run check` trong worktree riêng | Đạt; 346/346 Web tests, typecheck và boundary checks |
| `CORE_DOCUMENT_TEST=1`, Chrome thật, `npm.cmd run test:core` | Đạt; 28 nhóm HTTP và 13 nhóm browser, production live build/release scan, migration không drift, non-root, seed lặp và DB outage/recovery |
| PostgreSQL fixture Document qua `services/document/scripts/test-service.py --full-core` | Đạt; 25/25 Document tests, schema/role riêng |
| CI public interface gate `pytest tests/identity/test_public.py --cov=app.modules.identity.public --cov-branch --cov-fail-under=100` | Đạt; 17 tests, coverage 100% |
| Toàn bộ Core với `-W error`, branch coverage, JUnit và rule evidence trong cùng fixture | Đạt; 428 passed, 0 skipped, 0 failed scenarios; coverage tổng Core 91% |

Fixture backend được bọc thêm các lệnh CI (`alembic upgrade/check/heads`, maintenance report, coverage/JUnit và `tests/security/evidence.py`) trong container test. Lượt đầu có 428 tests pass nhưng pytest-cov không ghi được vào `/srv`; đã sửa test image dùng `/tmp`, chạy lại gate 100% và toàn suite thành công. Không hạ ngưỡng coverage hoặc dùng root cho app để né lỗi.

Tất cả tài khoản, tệp, SMTP TLS sink, PostgreSQL/volume và Chrome profile của các lượt này là fixture tổng hợp riêng. Log/screenshots ở Temp; không gửi Gmail thật hoặc dùng DB đang hoạt động. Các lượt backend/fullstack đã dọn container/volume và credential fixture. Các báo cáo ngày 22–23/10 vẫn là bằng chứng lịch sử của từng đợt, không thay cho kiểm chứng bản ghép này. Chưa chạy lại job tải tùy chọn 10 phút, không suy ra KPI hoặc full TP-01 từ regression.

## Review

Owner cần review trong PR: Identity/Common (TV1), Classroom/access (TV2), Social (TV3), Notification/Administration/shared CI–Compose (TV4), Document và Web. Báo cáo này không thay owner approval, nghiệm thu tải hoặc production readiness. AI/RAG vẫn thuộc TASK-018.
