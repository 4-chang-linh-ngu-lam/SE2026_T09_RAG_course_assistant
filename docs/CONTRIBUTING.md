# Quy trình cộng tác — Monorepo

## Branch, PR và commit
- Chỉ **một GitHub repository**. `main` là nhánh tích hợp; phát triển trên `feature/<issue>-<slug>` hoặc `fix/<issue>-<slug>`.
- Mỗi PR tập trung vào một chức năng/nhóm thay đổi có thể review và test; ít nhất **một reviewer khác tác giả**, CI/test liên quan đạt.
- **Squash merge** mặc định để lịch sử main gọn; không bắt buộc merge commit và **không commit theo từng file/task**. Không tạo commit giả để tăng thống kê.
- Không push trực tiếp main, force push nhánh chia sẻ hoặc tự thay đổi branch protection khi chưa thống nhất.

## Owner Core (trách nhiệm chính, không độc quyền)
| Thành viên | Module chính | Phối hợp |
|---|---|---|
| TV1 | identity | auth/security chung |
| TV2 | classroom | membership, quyền lớp |
| TV3 | social (feed/comments/calendar) | UI/API/test theo feature |
| TV4 | notification, administration | audit, CI/Compose, test tích hợp |

Các file `main.py`, `bootstrap.py`, `common/`, `pyproject.toml`, `Dockerfile`, `migrations/env.py`, `tests/conftest.py` là shared; thay đổi phải có review của người bị ảnh hưởng. Mỗi người vẫn làm frontend và test theo tính năng.

## Quy trình
1. Issue ghi mục tiêu, Business Rule ID, module, tiêu chí nghiệm thu.
2. Chốt API/public interface và fixture/mock trước khi code song song.
3. Làm feature branch, test, mở PR ghi thay đổi, ảnh hưởng DB/API, test đã chạy và rủi ro.
4. Review chéo, giải quyết conflict và comment, merge sau khi kiểm tra.
5. Migration Alembic mới cho thay đổi schema; không sửa revision đã merge/áp dụng; nếu nhiều head phối hợp merge revision.
6. Nếu đổi Business Rules hoặc contract: yêu cầu phê duyệt, cập nhật tài liệu/test cùng PR.

## PR checklist
- [ ] Có Issue/Rule ID và phạm vi rõ.
- [ ] Thay đổi shared interface/schema được thông báo và review.
- [ ] Test chạy thực tế, ghi kết quả.
- [ ] Không có secret, dữ liệu cá nhân hoặc chat riêng tư.
- [ ] Docs, migration, API contract đã đồng bộ.
