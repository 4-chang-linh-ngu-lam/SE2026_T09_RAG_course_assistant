# Kế hoạch Task tạm thời — RAG Course Assistant

**Version:** 0.1-draft | **Updated:** 2026-10-10 | **Status:** CHƯA CHỐT; cần review và ước lượng cùng nhóm.

> Đây là kế hoạch ở mức **Feature → Tasks**, không phải Task specification cuối cùng. Mỗi feature lớn có một branch, bên trong gồm nhiều Tasks nhỏ và các commit thực chất. **Không tạo 16 branch cùng lúc**. Tạo khi feature bắt đầu, merge qua PR và xóa sau khi hoàn tất. Các mốc W1–W12 chỉ là dự kiến, không trì hoãn công việc đã sẵn sàng để rải commit.

## Nguyên tắc và Definition of Done

- Nhóm có 4 người, mỗi người sở hữu nhóm module; cross-review tối thiểu một người khác.
- Feature phải có acceptance criteria theo Business Rules, API contract nếu liên quan, kiểm thử unit/integration, xử lý lỗi, tài liệu cập nhật và demo được.
- Từng Task có Issue ID, owner, ước lượng Story Points, dependency, Rule IDs, PR và bằng chứng test. **Chưa gán Story Points vì chưa review kỹ thuật/stack.**
- Merge commit, không squash. Không tự động coi số commit là công sức; không tạo commit giả.
- Có increment chạy được mỗi 1–2 tuần, đóng góp thực chất của từng thành viên xuyên kỳ.
- Khi feature quá lớn hoặc chặn consumer, tách PR/vertical slice độc lập; ưu tiên API contract/mock để song song.
- Mobile chỉ lên kế hoạch sau khi Web ổn định và nhóm xác nhận thời gian.

## Phân công đề xuất (có thể đổi sau khi biết năng lực và Story Points)

### TV1 — Identity & Classroom

#### CORE-01 — `feat/auth-and-users`
- **Mục tiêu:** Login, session, role/RBAC, profile.
- **Rule IDs:** F1,K2,A1. **Dự kiến:** W1–2.
- **Tasks tạm thời:**
  1. Xác định auth/session contract và role matrix.
  2. Triển khai login/logout và session validation.
  3. Thực thi RBAC tại Backend, kiểm tra unauthorized cases.
  4. Hoàn thiện giao diện và integration tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### CLS-01 — `feat/classroom`
- **Mục tiêu:** Course/class, join approval, co-lecturer, ownership, archive/restore.
- **Rule IDs:** A1–A6,H1–H2,M2,M5. **Dự kiến:** W1–4.
- **Tasks tạm thời:**
  1. CRUD course/class và quyền lecturer.
  2. Mã lớp, request/approve/reject, toggle join.
  3. Co-lecturer, membership/leave/remove.
  4. Ownership transfer, archive/restore, audit tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### CLS-02 — `feat/class-feed`
- **Mục tiêu:** Posts, comments, moderation.
- **Rule IDs:** G1,G2,L1,L5. **Dự kiến:** W4–5.
- **Tasks tạm thời:**
  1. Feed và quyền tạo/xóa bài.
  2. Comments, moderation, audit.
  3. Frontend + integration tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### SEC-01 — `test/class-access-regression`
- **Mục tiêu:** Permission/leave/archived-class security regression.
- **Rule IDs:** L2,H5,O2. **Dự kiến:** W7–9.
- **Tasks tạm thời:**
  1. Test cross-class membership và role escalation.
  2. Test archived/leave/revoked content.
  3. Khắc phục lỗi và chạy regression.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

### TV2 — Documents & AI Tutor

#### DOC-01 — `feat/document-library`
- **Mục tiêu:** Owner library, upload, formats, share, ACL.
- **Rule IDs:** B1–B3,B6,B7,O1. **Dự kiến:** W2–4.
- **Tasks tạm thời:**
  1. Owner library và metadata.
  2. Upload/validate 5 file formats.
  3. Sharing/revoke, owner vs co-lecturer permissions.
  4. Document browsing UI và access tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### DOC-02 — `feat/document-processing`
- **Mục tiêu:** Async extraction, statuses, retries, versions.
- **Rule IDs:** B4,B5,H3. **Dự kiến:** W3–5.
- **Tasks tạm thời:**
  1. Async job/status/retry.
  2. Extract PDF/PPTX/DOCX/TXT/MD, locators.
  3. Version switching và fallback ready.
  4. Error handling, observability, tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### RAG-01 — `feat/ai-tutor`
- **Mục tiêu:** Index/retrieve, citations, modes, class-bound chat.
- **Rule IDs:** C1–C6,B7. **Dự kiến:** W4–6.
- **Tasks tạm thời:**
  1. Chunk/index contract và embeddings.
  2. Class-scoped retrieval + current ACL recheck.
  3. Grounded generation/citation validation/abstention.
  4. Quick/tutor modes, chat UI, class-bound history.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### RAG-02 — `test/rag-evaluation`
- **Mục tiêu:** Retrieval benchmark, revoked-source tests, privacy redaction.
- **Rule IDs:** H4,K3,C2,C3. **Dự kiến:** W7–10.
- **Tasks tạm thời:**
  1. Tạo bộ đánh giá RAG và negative cases.
  2. Đo retrieval/citation/abstention/latency.
  3. Kiểm thử revoke, redaction, privacy và sửa lỗi.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

### TV3 — Learning Activities

#### QUIZ-01 — `feat/practice-quiz`
- **Mục tiêu:** Question bank, AI draft/lecturer approval, practice feedback.
- **Rule IDs:** D1–D3,D8. **Dự kiến:** W2–4.
- **Tasks tạm thời:**
  1. Question model và types.
  2. AI-generated draft + lecturer approval.
  3. Practice session, scoring, explanations.
  4. UI + tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ASM-01 — `feat/assessment`
- **Mục tiêu:** Author/publish, attempts, timer, auto-save, grading.
- **Rule IDs:** D4,D6,D7,I1–I3. **Dự kiến:** W4–6.
- **Tasks tạm thời:**
  1. Assessment authoring/config/assignment.
  2. Attempts/timer/server deadline/auto-save.
  3. Submit/timeout/reconnect/idempotency.
  4. Objective/subjective grading, publish result.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ASM-02 — `feat/assessment-lifecycle`
- **Mục tiêu:** Immutable versions, grade corrections, appeals, invalid questions.
- **Rule IDs:** I4,I6,I7,M4,O3,O4. **Dự kiến:** W6–8.
- **Tasks tạm thời:**
  1. Immutable published versions và version-bound attempts.
  2. Correction reason + audit + analytics update.
  3. Appeal workflow/late joiner handling.
  4. Invalidate/regrade/replacement question + notifications.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ASG-01 — `feat/assignment`
- **Mục tiêu:** Submission, late/resubmit, grading, reviews.
- **Rule IDs:** D5,I5,M1,M3,O5. **Dự kiến:** W5–7.
- **Tasks tạm thời:**
  1. Assignment authoring/deadline/late policy.
  2. Submission/resubmission/graded version.
  3. Lecturer grading/feedback/review.
  4. UI + integration tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

### TV4 — Learning UX, Analytics & Admin

#### UX-01 — `feat/learning-tools`
- **Mục tiêu:** Calendar, deadline notifications, personal notes/bookmarks.
- **Rule IDs:** G3–G5,H6,L3,L6,O2. **Dự kiến:** W2–5.
- **Tasks tạm thời:**
  1. Calendar/deadlines.
  2. In-app notification pipeline.
  3. Personal notes/bookmarks + revoked excerpts.
  4. Archived behavior + tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ANA-01 — `feat/analytics`
- **Mục tiêu:** Student/lecturer dashboards, evidence-based mastery.
- **Rule IDs:** E1–E3,J1–J3,O6. **Dự kiến:** W5–8.
- **Tasks tạm thời:**
  1. Student dashboard/grade timeline.
  2. Lecturer aggregate/individual progress.
  3. Topic evidence/insufficient data/small-cohort suppression.
  4. Analytics consistency tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ADM-01 — `feat/administration`
- **Mục tiêu:** Account actions, interventions, audit, privacy requests.
- **Rule IDs:** F1–F5,F7,K1–K6. **Dự kiến:** W4–8.
- **Tasks tạm thời:**
  1. Admin account lock/roles.
  2. Admin class intervention + audit.
  3. Verified privacy request workflows.
  4. Retention configuration and tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

#### ADM-02 — `feat/reports`
- **Mục tiêu:** Aggregate PDF/Excel and manual personal export workflow.
- **Rule IDs:** F6,O8. **Dự kiến:** W8–10.
- **Tasks tạm thời:**
  1. Aggregate report query/export PDF.
  2. Aggregate export Excel.
  3. Manual user export request tracking + tests.
- **Acceptance:** hành vi tương ứng được kiểm chứng bằng test/demo, không vi phạm Rule IDs; có PR review.

## Dependency và tích hợp

1. **CORE-01** phải thống nhất auth/RBAC contract sớm; không nhất thiết hoàn tất UI mới bắt đầu các module khác.
2. **CLS-01** cung cấp class/membership contract cho **DOC-01**, **RAG-01**, **QUIZ-01**, **ASM-01** và **ANA-01**.
3. **DOC-01 → DOC-02 → RAG-01** là dependency dữ liệu; có thể phát triển RAG trên fixtures/mock trước khi pipeline xử lý xong.
4. **QUIZ-01 → ASM-01 → ASM-02** chia sẻ question/attempt/grading contracts; Assignment có thể triển khai song song.
5. **ANA-01** cần grade events từ Quiz/Assessment/Assignment; sử dụng mock/contract test để không bị chặn.
6. **UX-01** notifications cần event contract từ Classroom/Assessment/Assignment; **ADM-01** audit phải tích hợp từ sớm, không đợi cuối kỳ.

## Increment đề xuất và chứng cứ đánh giá quá trình

| Mốc | Kết quả cần demo | Chứng cứ GitHub |
|---|---|---|
| W1–2 | Login + class skeleton + contracts + CI | PR của các owner, tests, API design |
| W3–4 | Class membership + document upload + practice question flow | Merged PR, test logs, demo |
| W5–6 | Tutor baseline + Quiz + Assessment/Assignment flow | End-to-end demo, PR/reviews |
| W7–8 | Quyền truy cập, grading edge cases, privacy, analytics | Regression suites, bugfix PR |
| W9–10 | RAG evaluation, dashboard/reporting, UX refinements | Benchmark, quality improvements |
| W11–12 | Web release; Mobile nếu đủ thời gian | Release notes, smoke tests, demo |

**Theo dõi hằng tuần:** mỗi người cập nhật Issues/Project với công việc đã làm, PR/commit/test/review thực tế; không hứa số commit tối thiểu hay thao túng lịch sử. Có thể điều chỉnh owner/feature nếu chênh lệch Story Points.

## Các quyết định còn cần nhóm xác nhận
- Stack, cơ sở dữ liệu, vector index, LLM, hosting, CI checks và deployment.
- Năng lực/tốc độ thực tế từng người, ước lượng Story Points và mức cân bằng.
- Độ lớn tối đa feature branch, cách chia vertical slice khi dependency kéo dài.
- Rubric chấm quá trình cụ thể của giảng viên.
- Mức ưu tiên và phạm vi Mobile cuối kỳ.

**Chưa tạo các file `TASK-*.md` riêng:** chỉ phân rã tạm thời theo yêu cầu, sẽ tách Task specs khi nhóm duyệt.
