# Quy trình cộng tác GitHub — RAG Course Assistant

**Status:** Đề xuất áp dụng sau khi nhóm review. **Nhóm:** 4 thành viên; môn học đánh giá quá trình.

## Branch strategy
- `main`: nhánh chính duy nhất tồn tại lâu dài, phải build/test được.
- **Một feature lớn = một branch**, có nhiều Task nhỏ và commit thực chất. Ví dụ: `feat/auth-and-users`, `feat/classroom`, `feat/documents`, `feat/ai-tutor`, `feat/assessment`.
- Sau khi merge, xóa branch; sửa lỗi/nâng cấp tạo `fix/<area>-<issue>`, `perf/<area>-<goal>`, `test/<area>-<scenario>`, `docs/<topic>`.
- Không tạo toàn bộ branch trước; chỉ tạo khi bắt đầu feature. Không dùng branch cố định theo tên thành viên.
- Nếu feature quá lớn hoặc chặn module khác, tách vertical slice thành feature/PR nhỏ hơn, không giữ branch kéo dài nhiều tuần.

## Issue → Task → Branch → Commits → PR → Review → Merge
1. Tạo Issue và liên kết `docs/tasks/TASK_PLAN.md`; Task có owner, Rule IDs, dependency, acceptance, test evidence.
2. Owner tạo feature branch từ `main` mới nhất; thống nhất API contract với người phụ thuộc trước khi code.
3. Mỗi Task nhỏ tạo commit có ý nghĩa, ví dụ `feat(documents): implement version history`, `test(rag): deny revoked documents`.
4. Mở Draft PR sớm khi cần trao đổi; chuyển ready khi feature/slice hoàn thiện.
5. PR ghi mục tiêu, Rule IDs, Architecture sections, Task IDs, ảnh/demo khi có UI, test và rủi ro/migration.
6. Tối thiểu 1 reviewer khác owner, CI xanh, giải quyết review comments; chọn **Create a merge commit**, không squash.
7. Xóa branch sau merge; cập nhật Issue/Project, changelog nếu cần.

## Bảo vệ main
Khuyến nghị ruleset: require PR, ít nhất 1 approval, required status checks, resolve conversations, block force push/delete. Tính khả dụng phụ thuộc quyền quản trị/gói GitHub. Không push trực tiếp main. Không cho agent tự merge hoặc tự thay đổi ruleset.

## Commit và đánh giá quá trình
- Mỗi người cấu hình GitHub email được xác minh, commit bằng danh tính thật của mình; không dùng tài khoản chung.
- **Không tạo commit giả, không trì hoãn merge để rải commit, không chia nhỏ vô nghĩa.**
- Nhóm hướng tới mỗi tuần mỗi người có hoạt động kỹ thuật được ghi nhận: code, test, docs, review, bug fixes; theo dõi cả PR/Issue/review thay vì chỉ đếm commits.
- Tích hợp increment chạy được mỗi 1–2 tuần, có demo/chứng cứ kiểm thử.
- Kiểm tra thực tế cách giảng viên tính commit và cách GitHub hiển thị contributions; không suy đoán.

## Multi-agent safety
Một người chịu trách nhiệm chính mỗi feature branch; nhiều agent nên dùng working tree/worktree riêng, tránh cùng sửa một file chưa đồng bộ. Agent chỉ sửa phạm vi Task; nếu gặp breaking change, dừng và đề xuất. Không tự sửa Business Rules, Architecture đã duyệt, migration dữ liệu nhạy cảm hoặc xóa file quan trọng.

## PR template
```md
## Mục tiêu và phạm vi
## Issue / Feature / Tasks
## Business Rules liên quan
## Architecture / API contracts
## Thay đổi chính
## Kiểm thử và bằng chứng
## Rủi ro, migration, bảo mật, dữ liệu
## Checklist
- [ ] Không thay đổi rule ngoài phạm vi được duyệt
- [ ] Đã kiểm tra quyền truy cập và trường hợp ngoại lệ
- [ ] Tests/build pass
- [ ] Đã tự review code AI-generated
- [ ] Docs/API contracts cập nhật nếu cần
```

## Quy tắc khi có xung đột
Ưu tiên cập nhật nhánh từ `main` và giải quyết conflict cẩn thận; không force push nhánh chia sẻ nếu chưa thống nhất. Thay đổi DB schema/API chung phải thông báo các owner liên quan. Quyền truy cập và versioned assessment phải được test sau mỗi lần tích hợp.
