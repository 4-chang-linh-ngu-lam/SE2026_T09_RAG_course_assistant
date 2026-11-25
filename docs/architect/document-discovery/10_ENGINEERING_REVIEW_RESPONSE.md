# DOC-00-R1 — Engineering Review Response

**Technical Lead review:** CONDITIONAL PASS
**Trạng thái:** DOC-00 — DISCOVERY APPROVED, CLOSED.
**Scope:** chỉ xử lý DOC-RV01–06; không chạy lại toàn bộ discovery, không sửa code/schema, không bắt đầu DOC-01.

Discovery được phê duyệt; implementation chưa được nghiệm thu; 48 DOC-T06 AC chưa VERIFIED; blockers/open decisions vẫn còn hiệu lực; DOC-01 chưa được phép bắt đầu.

| Review ID | Finding | Resolution | Evidence | Remaining Blocker | Status |
|---|---|---|---|---|---|
| DOC-RV01 | Đọc Core, Learning, Notification, System Integration mới nhất; cập nhật baseline/tác động Document. | FF pull tới c7f56c7; cập nhật baseline, API/security, deletion, cross-service dependencies và MIP trong discovery docs. | docs/architect/core-design/, learning-design/, notification-design/, system-integration/; document-discovery/00–09. | Design accepted chưa xác minh implementation/runtime. | RESOLVED IN DOCS |
| DOC-RV02 | Service JWT là system foundation, không có auth riêng trong Document. | DOC-03 chuyển thành adoption của SYS-02/CORE-T04 shared verifier; bỏ issuer/key management khỏi Document scope. | system-integration/00,02,08; core-design/00,04,06; backlog DOC-03. | Issuance/distribution/rotation và verifier code chưa được xác minh. | RESOLVED IN DESIGN; IMPLEMENTATION PENDING |
| DOC-RV03 | Reuse Core authorization qua adapter tương thích CORE-T03. | Xác nhận check_class_action có logic user/status/school/membership/assignment; Document gọi CORE-T03 REST, không import nội bộ; Document tự kiểm tra grant/version. | services/core/app/modules/classroom/public.py:113–174; schemas.py:19–26; router.py:482–493; core-design/04_INTERNAL_API.md; DOC-00 files 02–04, 08. | Current route là GET + X-Service-Key/action legacy. Mapping READ_DOCUMENT_SOURCE sang DOCUMENT_READ/SHARE/MANAGE chưa được chứng minh; CORE-T03 endpoint/registry chưa được xác minh trong code. | PARTIAL; ACTION MAPPING OPEN |
| DOC-RV04 | Durable deletion job, index cleanup/retry, retention và physical file cleanup. | Ghi DOC-OD-09: revoke ngay, durable/idempotent/restart-safe local cleanup, source vs AI index/temp ownership, ACK khác completion; không thêm bảng trong R1. | core-design/02,04,05; system-integration/03,09; notification-design/04,05; DOC-00 files 05,06,09. | Persistence schema, completion API/event, retries/dead-letter, retention 14 ngày scope, backup erasure/purge cần quyết định. | OPEN DECISION RECORDED |
| DOC-RV05 | Căn backlog theo Master Implementation Plan; phân biệt dependencies/parallel work. | Bổ sung phase mapping, shared foundations, task dependency table và parallel tasks; DOC-03 không còn xây Service JWT. | system-integration/08_MASTER_IMPLEMENTATION_PLAN.md; document-discovery/08_REVISED_IMPLEMENTATION_BACKLOG.md. | DOC-01 chưa được phép bắt đầu; contracts/foundations cần hoàn tất trước. | RESOLVED IN BACKLOG |
| DOC-RV06 | Giải thích test count RAG theo commit/scope nếu có bằng chứng. | Xác minh 15 file test_*.py tại 680beaf, 2d97551, dc0671c, c7f56c7; RAG test tree không đổi trong 2d97551..c7f56c7. | git ls-tree trên 4 refs; docs 01/07; git diff services/rag trống. | Báo cáo cũ ghi 21 nhưng nguồn/ref/scope không thấy trong các commit đã kiểm; không suy đoán nguyên nhân. | COUNT VERIFIED; OLD 21 UNRESOLVED |

## Git safety và pull

- Worktree D:/Workplace/SE2026_T09_RAG_course_assistant; branch codex/rag-technical-discovery.
- Pull --ff-only: HEAD từ 2d975514c4d017fe135b38df13652714b33433eb tới c7f56c722f421bf1df17f5a82f26a78682eb82be; local branch bằng origin/codex/rag-technical-discovery.
- origin/main: dc0671c36bf750ef914ac34d22e6ff2cf685287a.
- Fast-forward thêm 38 files, +667 dòng, toàn bộ tài liệu; không có application code changes trong pull.
- Giữ docs/architect/document-discovery/, docs/problem/ và stitch-rag-consistency.zip; không stage/commit/push/merge/rebase, không mở PR/deploy.
- Không chạy test, migration hoặc runtime trong DOC-00-R1.

**DOC-00 — DISCOVERY APPROVED, CLOSED.**
