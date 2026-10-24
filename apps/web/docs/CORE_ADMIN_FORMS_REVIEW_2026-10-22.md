# CORE-ADMIN-LIVE-VIEWS / Core.Administration Web presentation

**Trạng thái:** người dùng đã trả lời **“Cho phép AGY theo phạm vi này”**: cho AGY Flash đọc mã frontend và tài liệu hợp đồng liên quan, tạo duy nhất file trình bày cho ba form bên dưới; không gửi .env, token hoặc dữ liệu thật. AGY đã tạo file và hoàn tất một lượt sửa theo review Codex, đều SUCCESS/exit 0. Codex đã nối controller/session/route, kiểm tra boundary/TypeScript và 298 tests. Production HTTP evidence/readiness cuối cùng được ghi tại [báo cáo form live](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md); bản thân SUCCESS của worker không thay bằng chứng đó. Không mở rộng allowlist API hoặc file được giao cho AGY.

Read `D:/app/cnpm/SE2026_T09_RAG_course_assistant/.agents/skills/lumi-frontend-orchestrator/SKILL.md`. This is a bounded UI generation task; Codex owns controllers, auth, API calls, data integration and tests.

## Baseline and authority

Branch frontend1, HEAD 9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8 plus substantial pre-existing work. Current verified baseline: 286 frontend tests; production live build and 21 real HTTP groups passed, including all three prepared controllers. User explicitly approved the 38 existing Core APIs on 2026-10-22, see apps/web/docs/CORE_REMAINING_CONTRACT_REVIEW_2026-10-22.md, and now explicitly authorized sending this bounded frontend/contract context to AGY. Identity-only notes in older AGENTS snapshots are superseded only for those approved existing APIs.

Sources: root AGENTS.md, apps/web/AGENTS.md, docs/architect/BUSINESS_RULES.md, apps/web/docs/FRONTEND.md, apps/web/src/lib/api/core-contract.ts, apps/web/src/lib/core-admin-controller.ts. Look at existing accounts forms/shared ui for styling. Read absolute paths using file tools only; no shell/terminal/RunCommand.

## Editable scope (one file only)

Create `D:/app/cnpm/SE2026_T09_RAG_course_assistant/apps/web/src/features/administration/core-admin-views.tsx`.
Do not write any other file. Use existing shared classes/card/table/form-stack/button/notice, accounts-panel, accounts-table-scroll. No custom CSS needed. No network calls, storage, adapter imports, controller creation, business logic, fake data, Git operations, backend changes, API changes or dependencies.

## Exact interface to implement

`'use client'`; imports React local form state, `CoreAdminState, StaffDraft, ResolutionDraft` from `@/lib/core-admin-controller`, `AdminReason` type from `@/lib/api/operations`; optional shared UI Dialog/ErrorNotice/StatePanel. Export these THREE presentational components:

1. `CoreStaffInviteView({state,onSubmit}:{state:CoreAdminState;onSubmit(input:StaffDraft):void})`.
Form email, checkboxes LECTURER/ADMIN (default LECTURER), reason enum selector, submit. Local input state only. Submit passes `{email,roles,reason}`. Display returned staff id/email/status after confirmation; do not claim delivery to an external inbox. Core sends an invitation link; NEVER display a raw token, synthetic invitation id/expiry, resend/revoke/list controls (those APIs do not exist). Unknown staff result must block re-submit and explain manual checking before any repeat. Busy blocks double submit. No session data or credentials stored.

2. `CoreImportView({state,onPreview,onConfirm,onReconfirm,onClearCodes}:{state:CoreAdminState;onPreview(file:File):void;onConfirm(reason:AdminReason):void;onReconfirm(reason:AdminReason):void;onClearCodes():void})`.
Select original CSV/XLSX File, click preview; explain file max 2,000,000 bytes and 100 rows, first row exact columns `username` required, `display_name` and `user_id` optional, username cells text. No client column-mapping or partial-row import (server validates whole file). Render returned preview_id, expiry, items (row/action/username/user_id) and row errors. Confirm only when preview.valid and preview_id exist, reason selected, an explicit checkbox acknowledges creating/updating these rows. Do not invent display_name in preview. Show receipt status, replayed, items row/outcome/student.username/student.id/code/expiry. Codes are one-time sensitive Admin disclosure, only render actual non-null code; never persist/download/log, and provide `onClearCodes` with label acknowledging safe handoff. Replayed code=null must say no code is disclosed again, never fabricate one.
For unknown confirm only, offer explicit `onReconfirm(reason)` action labelled e.g. “Xác nhận lại theo mã phiên nhập”, with explanation that it MAY complete the import or return an existing durable receipt, and a replay does not disclose codes again. It is a deliberate mutation, NEVER label it read-only “check status”. Keep same selected reason while unknown. No automatic retries/effects invoking commands. Disable unrelated submissions while busy/unknown or until receipt codes are acknowledged/cleared. For unknown preview, show an honest warning, no guessed account success. No job/history/resume endpoint exists.

3. `CoreDataRequestsView({state,onReload,onSelect,onResolve}:{state:CoreAdminState;onReload():void;onSelect(id:string):void;onResolve(input:ResolutionDraft):void})`.
Read-only list of actual `state.requests` fields (id,user_id,type,status,created_at), loading/empty/error and Reload. Select via onSelect; show actual selected detail reason/status/resolution_note. Form status IN_REVIEW/COMPLETED/REJECTED; resolution_note enum choices VERIFICATION_IN_PROGRESS/POLICY_PENDING/OUTSIDE_CORE_SCOPE/INSUFFICIENT_VERIFICATION/REQUEST_REJECTED/DUPLICATE_REQUEST; checkbox identity_verified; reason enum. onResolve sends snake_case fields plus reason. A requested COMPLETED can return IN_REVIEW/POLICY_PENDING: always display state.selected's actual server result and explain that final data processing is not available yet. No fabricated identityVerified/revision/classification/processing status, no execute/export/delete-all/download controls. Unknown resolve blocks mutations until explicit onReload reads current server state for review; never resend automatically. Busy guards buttons. An existing selected row remains read-only while reloading.

All three use Vietnamese labels. Reason enum options: ADMIN_INTERVENTION “Can thiệp quản trị”, USER_REQUEST “Theo yêu cầu người dùng”, POLICY_VIOLATION “Vi phạm chính sách”. Display state.issue.message and optional correlationId as plain text; do not infer success from absence of error. Support keyboard labels, accessible status/alert and responsive scrollable tables. Local form state contains no access token or code. Codex will mount/key by actor and own all action guards.

## Done and blocked conditions

Working presentational file with exact exports/interfaces. Reuse established styles; no new layout system. Missing APIs are not blockers for these three bounded views because unsupported controls must be absent. Do not change controller/type files to fit your UI; report an interface mismatch instead. No tests claimed unless actually run; shell tools prohibited. Return changed path, brief behavior and unverified browser status. Codex reviews all changes and runs checks/build/HTTP.

## Review và sửa sau lần sinh đầu

- Import: khóa chọn file khi đã có preview; “Chọn tệp khác” xóa preview/ack/file trước khi kiểm tra lại, kể cả file mới trùng tên. Không cho xác nhận nhầm preview cũ.
- Review data-request: reset ô xác nhận danh tính và draft khi selected request ID đổi; controller bỏ selected cũ trước GET mới và không giữ dữ liệu/action sau read 401/403.
- Bỏ thuật ngữ triển khai khỏi hướng dẫn sản phẩm; giữ các giới hạn file/cột và quyết định có ý nghĩa với Admin. Nhãn COMPLETED của hành động là “Đề nghị hoàn tất”; kết quả vẫn dùng status/note server.
- Requests có h1, chi tiết UUID wrap và bảng cuộn. Thêm React import để chạy render test bằng tsx hiện có.
- Worker chỉ sửa `src/features/administration/core-admin-views.tsx`; Codex tự viết wrapper, scope guard, navigation/dispatch, tests và HTTP renderer. Hai log AGY riêng ở máy người dùng ghi lần sinh 23:24:00 và sửa 23:31:09 ngày 22/10/2026; không đưa log chứa context vào repo.
