# LUMI FRONTEND — PERFORMANCE & INTERACTION AUDIT

Ngày audit: 2026-10-21. Owner/Final reviewer: Codex. Phạm vi: mã nguồn cục bộ `apps/web` của `D:/app/cnpm/SE2026_T09_RAG_course_assistant`.

**Trạng thái: AUDIT COMPLETE / IMPLEMENTATION NOT STARTED.** Báo cáo và harness đo được tạo; không sửa mã sản phẩm, backend, business rules, package, cấu hình model/provider hay security gates. Không chạy bất kỳ thao tác Git nào. SHA256 đối chiếu **257 file source/config/test: 0 thay đổi, 0 file bị xóa**. Build/dev output nằm trong harness bên ngoài source.

## A. Executive Summary

Frontend có lỗi tương tác thật, cùng một số lựa chọn kiến trúc làm việc chuyển màn có cảm giác chậm. Không có bằng chứng một nguyên nhân duy nhất giải thích mọi độ trễ.

1. **P1 — Search mất ký tự:** AccountList dùng URL làm giá trị input, gọi `router.replace()` trên mỗi phím. Gõ `minh.anh10a1` ở khoảng cách 20 ms/phím, cả **3/3 lần** chỉ còn `1`. Mỗi lần có 13 request tài nguyên/navigation trong harness, **0 Accounts/workspace port call**. Đây là lỗi đồng bộ input/navigation, không phải API search chậm.
2. **P1 — Load thêm do object identity:** `effectiveParams` mới ở mỗi render parent; effect Analytics và Assignment phụ thuộc raw `params`. Snapshot workspace hoàn tất làm effect đọc lại cùng scope. Quan sát development: **3 lần feature load**, trong khi Assessment dùng key nguyên thủy có **2 lần** do StrictMode. Không phải vòng lặp vô hạn; cập nhật state con không render ngược parent.
3. **P1 — Assessment kẹt “Đang lưu…”:** offline → sửa đáp án → online → đối soát trả IN_PROGRESS có đáp án chưa lưu. `saving` bị gán bằng `dirty`, dù không có write. Browser xác nhận nút lưu bị khóa; chỉ có 1 reconcile, **0 saveAnswers đang chạy**.
4. **P1 — Query cục bộ kéo theo workspace reload:** đổi câu Practice gọi `history.pushState(?question=…)`; RouteScreen vẫn bắt thay đổi query. Một lần chuyển câu đã quan sát **1 workspace.load**. Reader đổi trang cũng tải lại model; đây cần cân nhắc hợp đồng phân trang/quyền nguồn, không xóa mọi revalidation một cách máy móc.
5. **P1 UX — Loading làm mất continuity:** snapshot không trùng key lập tức thành `null`; ClassHeader/tabs biến mất và feature đổi sang StatePanel, kể cả sau mutation đã ACK. Feature key ổn định chưa đủ để giữ cây DOM con khi nhánh render trả loading.
6. **P2 — Submit có thể chờ save trùng:** khi cùng bộ đáp án đã đang lưu, Submit enqueue lại trước flush. Probe trực tiếp class hiện có xác nhận **2 write liên tiếp, payload giống nhau**, revision tăng hai lần. Không gọi đây là tự retry submit; submit và save là hai mutation khác nhau.
7. **Development overhead có số đo:** lần đầu vào các tab Student trên output dev mới có upper bound click-to-content khoảng **2.34–4.07 giây**, gồm biên dịch. Warm overview/feed ở cùng môi trường có median khoảng **0.28–0.33 giây**. Những con số dev không đại diện backend hoặc production.

**P0:** chưa xác minh lỗi P0 trong phạm vi audit. **Chưa chứng minh:** backend thật chậm, session restore trên mỗi tab, tải lại JS dynamic chunk trên mỗi lần quay lại, vòng lặp load vô hạn, hydration mismatch hoặc React commit quá dài. Live adapter phần lớn domain còn `pending-contract`; không có API business thật để benchmark các domain đó.

### Phương pháp và giới hạn số đo

- Đọc root/web AGENTS, skill + baseline/task contract/quality gates, BUSINESS_RULES, FRONTEND.md, port/integrations/live/mock adapters, Identity API contract và route/navigation/feature implementations. Toàn bộ 71 route được inventory và đối chiếu loader/feature ownership; không đồng nghĩa mọi trạng thái được browser test.
- Chrome cài sẵn chạy headless qua Python Playwright có sẵn; viewport 1440×1000, không throttle CPU/network. Accounts và share dialog còn kiểm tra geometry tại 1440/768/390/320. Không cài package.
- Có hai preview cũ cùng output `.next-preview`; lần đo đầu bị mất phiên nên loại khỏi benchmark. Một thử nghiệm junction cả `app` không được Next scanner nhận route cũng bị loại. Không quy các thất bại harness này thành bug ứng dụng.
- Harness cuối: `D:/app/web/2010/artifacts/lumi-perf-audit/preview-app-v2`. Các route wrappers/layout/CSS trong `app` được copy byte-identical từ source; `src/dev/config/scripts/node_modules` liên kết tới mã hiện có. Chỉ config/output/generated typings của harness được ghi. Preview `:4186`; live build/start `:4187`. Không copy `.env`, secret hay source từ nơi khác.
- Tạm instrument adapter **trong browser test**, chỉ đếm method/route/start/end; không thay dữ liệu trả về. `workspace.load` trong mock là lời gọi in-memory, không phải HTTP. Network tách RSC/CSS/JS khỏi `/api/v1`.
- Click-to-feedback là thời điểm main-content text mutation được quan sát ở frame kế sau click. Đây là proxy DOM feedback, không chứng minh từng pixel đã paint. Click-to-content là **upper bound**: chờ đúng pathname + workspace đúng route đã hoàn tất + hết loader đang hiển thị, sau đó thêm 80 ms và overhead polling (live harness 60 ms). Không gọi upper bound là latency paint chính xác.
- Các sample `*-first` ở lượt chạy lại là lần đầu trong browser context, server có thể đã compile. Chỉ bảng exploratory cold ghi rõ các route được compile trên output mới. Không gộp hai nhóm.
- Mỗi warm pair có 5 mẫu/role. Chỉ báo median/min–max; **không p95**, không phần trăm tăng tốc tùy ý. Event Timing/long tasks không thay thế field INP. Không đo React commit duration bằng React Profiler, CPU trace attribution, heap leak hoặc field Core Web Vitals.
- Production-like dùng **live bundle** và một browser HTTP stub riêng cho đúng `/auth/refresh`, `/users/me`. Các domain vẫn unavailable đúng live adapter. Nó chỉ đo shell/navigation/runtime, không phải luồng lớp học đầy đủ, không phải backend thật, không phải mock production build.

### Hypothesis disposition

| Giả thuyết ban đầu | Kết luận đã đối chiếu |
|---|---|
| PERF-001 luôn workspace.load | CONFIRMED trên protected route; không có settled cache ở RouteScreen. Đây vừa là chi phí vừa là lựa chọn fail-closed. |
| PERF-002 hai tầng load trùng | PARTLY CONFIRMED: phần lớn chạy song song, không phải parent chặn tất cả feature. Có payload bỏ đi, summary lặp và riêng Practice Editor có projection đầy đủ lặp. |
| PERF-003 search/filter navigation | CONFIRMED và có lỗi mất ký tự. `q/group/status` không nằm SAFE_ROUTE_QUERY_KEYS nên không tự refetch workspace; `page` thì có. |
| PERF-004 dependency params | CONFIRMED cho Intelligence và Assignment; không infinite loop. Điều kiện phát sinh phụ thuộc feature đã mount trước parent snapshot ACK. |
| PERF-005 dynamic imports chậm lặp | NOT_REPRODUCED cho tải lại JS khi warm. Có cold compile/module cost và cơ hội giảm entry chung; chưa chứng minh bundle là bottleneck chính. |
| PERF-006 restore session mỗi tab | NOT_REPRODUCED. Provider ở root; live identity coalesces restore/refresh. 10 navigation live shell không phát sinh thêm auth HTTP. |
| PERF-007 loading dư thừa | CONFIRMED snapshot-null/UI continuity; không có minimum artificial spinner delay chung. |

## B. Route Performance Matrix

**W** = `adapter.workspace.load`; **∥** = effect độc lập chạy song song; **→** = phụ thuộc/đợi bước trước. Các số là upper bound click-to-content của browser preview; `B` là mở trực tiếp trong browser, `S` chỉ static audit. Route matrix không coi live unavailable là backend nghiệp vụ đã triển khai. Finding `014?` còn cần tái hiện đầy đủ.

| Route / ID | Role | Load pattern | Duplicate work / evidence | Measured latency | Issue |
|---|---|---|---|---|---|
| `/login` · `auth.login` | public | Auth UI; session root restore | Không chứng minh duplicate request | B: timing chưa lấy mẫu | 005 opportunity; 006 restore expected |
| `/activate` · `auth.activate` | public | Auth UI; session root restore | Không chứng minh duplicate request | S: chưa đo browser | 005 opportunity; 006 restore expected |
| `/staff/invitation` · `auth.invitation` | public | Auth UI; session root restore | Không chứng minh duplicate request | S: chưa đo browser | 005 opportunity; 006 restore expected |
| `/recover` · `auth.recover` | public | Auth UI; session root restore | Không chứng minh duplicate request | S: chưa đo browser | 005 opportunity; 006 restore expected |
| `/reset-password` · `auth.reset` | public | Auth UI; session root restore | Không chứng minh duplicate request | S: chưa đo browser | 005 opportunity; 006 restore expected |
| `/student` · `s.home` | STUDENT | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: timing chưa lấy mẫu | 001/007 |
| `/student/classes` · `s.classes` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤520 ms, n=1 | 001/007 |
| `/student/classes/:classId/overview` · `s.overview` | STUDENT | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: median ≤327 ms, n=5 | 001/007 |
| `/student/classes/:classId/feed` · `s.feed` | STUDENT | W → feature view | Không chứng minh duplicate request | B: median ≤279 ms, n=5 | 001/007 |
| `/student/classes/:classId/documents` · `s.documents` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤270 ms, n=1 | 001/007 |
| `/student/classes/:classId/documents/:documentId` · `s.reader` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤506 ms, n=1 | 001/007, 008 |
| `/student/classes/:classId/tutor` · `s.tutor` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤892 ms, n=1 | 001/007, 008 |
| `/student/classes/:classId/practice` · `s.practice` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤691 ms, n=1 | 001/007 |
| `/student/classes/:classId/practice/:practiceId/attempts/:attemptId` · `s.practiceAttempt` | STUDENT | W → feature view | Không chứng minh duplicate request | B: timing chưa lấy mẫu | 001/007, 008, 013, 014? |
| `/student/classes/:classId/practice/:practiceId/attempts/:attemptId/result` · `s.practiceResult` | STUDENT | W → feature view | Không chứng minh duplicate request | S: chưa đo browser | 001/007 |
| `/student/classes/:classId/assessments` · `s.assessments` | STUDENT | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | B: ≤837 ms, n=1 | 001/007, 002 |
| `/student/classes/:classId/assessments/:assessmentId` · `s.assessment` | STUDENT | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | B: timing chưa lấy mẫu | 001/007, 002 |
| `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId` · `s.examAttempt` | STUDENT | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | B: timing chưa lấy mẫu | 001/007, 002, 009, 010, 013 |
| `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/receipt` · `s.receipt` | STUDENT | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/result` · `s.examResult` | STUDENT | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/student/classes/:classId/assignments` · `s.assignments` | STUDENT | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | B: ≤840 ms, n=1 | 001/007, 002, 004 |
| `/student/classes/:classId/assignments/:assignmentId` · `s.assignment` | STUDENT | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/student/classes/:classId/calendar` · `s.calendar` | STUDENT | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: ≤590 ms, n=1 | 001/007 |
| `/student/classes/:classId/progress` · `s.progress` | STUDENT | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | B: ≤846 ms, n=1 | 001/007, 002, 004 |
| `/student/notes` · `s.notes` | STUDENT | W → feature view | Không chứng minh duplicate request | B: ≤613 ms, n=1 | 001/007 |
| `/student/history/classes/:classId` · `s.history` | STUDENT | W → feature view | Không chứng minh duplicate request | S: chưa đo browser | 001/007 |
| `/student/history/results/:resultId` · `s.historyResult` | STUDENT | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/account` · `account.profile` | STUDENT/LECTURER/ADMIN | W ∥ session-backed profile | Không chứng minh duplicate request | S: chưa đo browser | 001/007, 002 |
| `/account/data-requests` · `account.requests` | STUDENT/LECTURER/ADMIN | W ∥ Identity requests controller | Không chứng minh duplicate request | S: chưa đo browser | 001/007, 002 |
| `/notifications` · `account.notifications` | STUDENT/LECTURER/ADMIN | W → feature view | Không chứng minh duplicate request | B: ≤601 ms, n=1 | 001/007 |
| `/calendar` · `account.calendar` | STUDENT/LECTURER | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: ≤548 ms, n=1 | 001/007 |
| `/teacher` · `t.home` | LECTURER | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: timing chưa lấy mẫu | 001/007 |
| `/teacher/classes` · `t.classes` | LECTURER | W → feature view | Không chứng minh duplicate request | B: median ≤416 ms, n=2 | 001/007 |
| `/teacher/classes/:classId/overview` · `t.overview` | LECTURER | W → scoped calendar/learning projections (preview) | Calendar projection lặp trong metrics/overview | B: median ≤302 ms, n=5 | 001/007, 011 |
| `/teacher/classes/:classId/feed` · `t.feed` | LECTURER | W → feature view | Không chứng minh duplicate request | B: median ≤309 ms, n=5 | 001/007 |
| `/teacher/classes/:classId/calendar` · `t.calendar` | LECTURER | W → scoped calendar/learning projections (preview) | Không chứng minh duplicate request | B: ≤2178 ms, n=1 | 001/007 |
| `/teacher/classes/:classId/documents` · `t.documents` | LECTURER | W → feature view | Không chứng minh duplicate request | B: ≤818 ms, n=1 | 001/007 |
| `/teacher/classes/:classId/tutor` · `t.tutor` | LECTURER | W → feature view | Không chứng minh duplicate request | B: ≤2886 ms, n=1 | 001/007 |
| `/teacher/classes/:classId/activities` · `t.activities` | LECTURER | W → Assessment/Assignment lists ∥ | Không chứng minh duplicate request | B: ≤2634 ms, n=1 | 001/007 |
| `/teacher/classes/:classId/practice/:practiceId/edit` · `t.practiceEditor` | LECTURER | W ∥ PracticeAuthoring.load → W (preview) | Parent editor projection + authoring snapshot → W | S: chưa đo browser | 001/007, 002 |
| `/teacher/classes/:classId/assessments/:assessmentId/edit` · `t.assessmentEditor` | LECTURER | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/teacher/classes/:classId/assessments/:assessmentId/review` · `t.assessmentApproval` | LECTURER | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/teacher/classes/:classId/assignments/:assignmentId/edit` · `t.assignmentEditor` | LECTURER | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/classes/:classId/grading` · `t.gradingQueue` | LECTURER | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/classes/:classId/assignments/:assignmentId/submissions/:submissionId/grade` · `t.assignmentGrading` | LECTURER | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/classes/:classId/assessments/:assessmentId/attempts/:attemptId/grade` · `t.examGrading` | LECTURER | W ∥ Assessment.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/teacher/classes/:classId/appeals/:appealId` · `t.correction` | LECTURER | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/classes/:classId/grade-proposals/:proposalId/review` · `t.correctionApproval` | LECTURER | W ∥ Assignment.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/classes/:classId/analytics` · `t.analytics` | LECTURER | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | B: ≤2520 ms, n=1 | 001/007, 002, 004 |
| `/teacher/classes/:classId/analytics/students/:studentId` · `t.studentAnalytics` | LECTURER | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |
| `/teacher/library` · `t.library` | LECTURER | W → feature view | Không chứng minh duplicate request | B: ≤1369 ms, n=1 | 001/007 |
| `/teacher/library/:documentId` · `t.libraryDocument` | LECTURER | W → feature view | Không chứng minh duplicate request | B: ≤2527 ms, n=1 | 001/007, UX-001 |
| `/admin/accounts` · `a.accounts` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | B: ≤261 ms, n=1 | 001/007, 002, 003 |
| `/admin/accounts/:userId` · `a.account` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/accounts/legacy` · `a.legacy` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/accounts/students/new` · `a.newStudent` | ADMIN | W ∥ provisioning form | Không chứng minh duplicate request | S: chưa đo browser | 001/007, 002 |
| `/admin/accounts/staff/invitations` · `a.staffInvite` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/imports/new` · `a.importNew` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | B: ≤1779 ms, n=1 | 001/007, 002 |
| `/admin/imports/:importId` · `a.import` | ADMIN | W ∥ Accounts.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/catalog` · `a.catalog` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | B: ≤1616 ms, n=1 | 001/007, 002 |
| `/admin/homerooms` · `a.homerooms` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | B: ≤1468 ms, n=1 | 001/007, 002 |
| `/admin/homerooms/:homeroomId` · `a.homeroom` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/classes` · `a.classes` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | B: ≤1831 ms, n=1 | 001/007, 002 |
| `/admin/classes/new` · `a.newClass` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/classes/:classId/settings` · `a.classSettings` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/classes/:classId/enrollment` · `a.enrollment` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/classes/:classId/lifecycle` · `a.lifecycle` | ADMIN | W ∥ Classroom.load | W + self-load; không mặc định cùng payload | S: chưa đo browser | 001/007, 002 |
| `/admin/data-requests` · `a.dataRequests` | ADMIN | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | B: ≤1780 ms, n=1 | 001/007, 002, 004 |
| `/admin/audit` · `a.audit` | ADMIN | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | B: ≤1712 ms, n=1 | 001/007, 002, 004 |
| `/admin/reports` · `a.reports` | ADMIN | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | B: ≤1843 ms, n=1 | 001/007, 002, 004 |
| `/admin/reports/exports` · `a.exports` | ADMIN | W ∥ Intelligence.load | Dev: có extra load sau W ACK (004) | S: chưa đo browser | 001/007, 002, 004 |

Inventory: **71 route definitions**, **72 App Router page files** (`/` là session redirect phụ), 5 public + 66 protected. Shared account routes có nhiều role, nên tổng các cột role không cộng thành 71. API proxy, error/loading/not-found không tính thành product route.

### Browser benchmark đã đo

| Môi trường / thao tác | n | Feedback median | Content upper-bound median | Content min–max |
|---|---:|---:|---:|---:|
| Dev preview · STUDENT · overview-warm | 5 | 156.4 ms | ≤326.7 ms | ≤210.3–429.6 ms |
| Dev preview · STUDENT · feed-warm | 5 | 160.9 ms | ≤279.3 ms | ≤197.3–323.6 ms |
| Dev preview · LECTURER · overview-warm | 5 | 136.7 ms | ≤302.3 ms | ≤242.9–415.6 ms |
| Dev preview · LECTURER · feed-warm | 5 | 141.2 ms | ≤308.8 ms | ≤195.9–321.0 ms |
| Live shell + Identity stub · `/student/classes` | 5 | 12.3 ms | ≤105.9 ms | ≤82.0–120.7 ms |
| Live shell + Identity stub · `/student` | 5 | 12.0 ms | ≤94.7 ms | ≤87.5–110.9 ms |
| Dev · Admin mở dialog tài khoản | 1 | 16.5 ms | ≤121.3 ms | Một sample, không percentile |

Cold exploratory trên output dev mới: feed ≤2342 ms, documents ≤2581 ms, tutor ≤2488 ms, practice ≤2864 ms, assessments ≤2630 ms, assignments ≤4070 ms, calendar ≤3915 ms, progress ≤2931 ms (mỗi route n=1). Chỉ giữ các action có port route đúng với route đích; đoạn notifications/notes của harness cũ bắt readiness quá sớm đã bị loại. Cold numbers giúp nhận diện compile overhead, chưa phải benchmark lặp đủ để dự báo.

Warm feed: mỗi action có 1 fetch RSC + 1 stylesheet request trong dev, **0 business HTTP**, **0 JS chunk mới**; có 2 workspace port calls do dev StrictMode. Không gọi RSC + stylesheet là “hai API trùng”.

Trong các phiên quan sát có long tasks >50 ms: Student 20 (max 323 ms), Teacher 16 (max 277 ms), Admin 9 (max 331 ms). Chưa có CPU stack attribution nên không gán các long task cho một component cụ thể. Live shell stub trong sample không ghi long task >50 ms, max Event Timing 16 ms; không suy rộng thành INP production. LCP live shell một document là 508 ms trong môi trường local/stub, không phải KPI sản phẩm.

Build live được Next báo **First Load JS 152 kB** cho login/student/admin accounts/library; shared runtime **103 kB**. Tổng tất cả CSS chunks trên disk 142,003 byte raw / 33,878 byte gzip độc lập từng file; initial Student shell thực sự tải 8 stylesheet với tổng encodedBodySize khoảng 21.3 kB. Tổng toàn bộ chunks không phải dung lượng tải của một route. Không có bằng chứng font tải từ CDN gây chậm; globals dùng system font, report font nằm preview adapter.

## C. Interaction Audit Matrix

`B` = thực hiện browser; `C` = kiểm tra source/port/controller và tests hiện có; `U` = hành vi cần đo bổ sung. Cột expected mô tả tiêu chí sửa, không tuyên bố đã đạt.

| Action | Screen / role | Current behavior | Expected behavior | Issue / evidence | Priority |
|---|---|---|---|---|---|
| Login, restore | Public/all | Refresh → me có phụ thuộc token; credential queue/generation và single flight | Giữ serialization, phản hồi submit ngay, không replay mutation | B/C: initial live stub 2 HTTP, nav không restore lại | P3 / expected |
| Sidebar chuyển trang | All | Link → RSC → client effect → W, snapshot riêng page | Có pending feedback; shell ổn định theo scope | B/C 001/007 | P1 UX |
| Tabs cùng lớp | Student/Teacher | Header/tabs mất trong null snapshot; warm vẫn W | Giữ vị trí bố cục, không flash toàn vùng nếu chỉ cập nhật cục bộ | B warm pairs / 007 | P1 |
| Đổi lớp | Student/Teacher | resource path + feature key đổi, load mới | Bỏ data scope cũ ngay; không cache chéo lớp/actor | C; browser đổi hai lớp chưa đo | P2 / U |
| Back/Forward | All | React page/draft lifecycle; không có route data cache trong app | Khôi phục local state hợp lệ, revalidate nguồn đúng quyền | B basic back/forward; dirty/race chưa browser exhaustive | P2 |
| Search gõ nhanh | Admin Accounts | Controlled value lấy từ URL, replace từng ký tự; 3/3 mất chuỗi | Local input cập nhật ngay, URL đồng bộ có kiểm soát, IME nguyên vẹn | B 003 | P1 |
| Group/status filters | Admin Accounts | Local filter nhưng query navigation cho từng thay đổi | Phản hồi list tức thì; không tải lại dataset không cần thiết | C/B search pacing; group/status chỉ C | P2 |
| Phân trang | Admin Accounts | Slice 10 rows; `page` gây W lại, Accounts scope không reload | Đổi slice/URL cục bộ, không đọc workspace rỗng | C 001/002/003 | P2 |
| Mở/đóng account detail | Admin Accounts | setSelectedId, native dialog; không adapter call | Local feedback ngay, Escape/focus đúng | B: 16.5 ms proxy feedback, Escape đóng | P3 |
| CSV/XLSX chọn tệp | Admin Import | arrayBuffer → decode/parse; XLSX lazy import; chưa giới hạn bytes/rows ở reader | Giới hạn hợp lý theo contract, cancel/stale guard; stress test trước worker/virtualization | C 013 | P2 opportunity |
| Mapping/preview import | Admin Import | Local mapping; preview adapter mutation rồi navigate | Feedback busy, không fake import; tránh load toàn Accounts trước file picker | C 002 | P2 |
| Confirm import | Admin Import | Revision/accountRevision + reconcile, không blind retry | Giữ unknown outcome và one-time handoff | C/tests; B chưa thực hiện mutation | correctness retained |
| Catalog/Homerooms/Class list | Admin | W + classroom loader; filters local, full workspace payload | Bỏ W thừa, pagination khi có stress evidence | B list routes; edit forms C | P2 |
| Roster/enrollment preview/confirm | Admin | Preview → confirm dependent revision, busy + unknown controls | Không parallel hóa hai bước có phụ thuộc; không bỏ confirm | C/tests, B chưa mutation | expected safety |
| Archive/restore | Admin | Confirmation/revision + reload | Giữ audit/quyền hiện hành, invalidate affected scopes | C/tests | P2 integration |
| Admin History | Admin | render toàn items, format Intl từng item; CSS scoped | Chỉ paginate/virtualize nếu số lượng/trace chứng minh | C; không có benchmark large history | P3/U |
| Library search/filter | Teacher | Local state lọc tài liệu, không router trên mỗi phím | Giữ local responsiveness, memo chỉ khi đo cần | C/B library open, search chỉ C | P3 |
| Upload mới/version | Teacher | Validation + busy; ACK rồi W reload | Giữ validation/unknown semantics, feedback scoped, không giả success | C/tests; lần audit không upload | P2/007 |
| Mở share dialog | Teacher Document | Local state, 0 port call; native modal | Không cần network để mở; focus/keyboard rõ | B: 2 checkbox; width 1440/768/390/320 không root overflow | P3 |
| Cấp/thu hồi chia sẻ | Teacher Document/Class | Guard permission/current class; confirm revoke; ACK → reload | Giữ confirm/unknown/no retry; quyền nguồn mất phải ẩn ngay | C/tests; lần audit không share/revoke mutation | P1 UX/007, correctness retained |
| Cancel revoke / delete | Teacher Document | Đóng local modal, busy ngăn đóng khi mutation | Không mutation khi Cancel; không fake success | C; Escape share B | expected |
| Retry processing | Teacher Library/Detail | Mutation + full snapshot reload | Rõ phiên bản đích, busy scoped; không retry unknown tự động | C/tests | P2/007 |
| Reader đổi trang | Student | setPage + router.replace(page/version) → W | Giữ local page UI nếu model/permission hợp lệ; scope version thật vẫn reset | B: 1 W/page change; 008 | P2 |
| Reader ghi chú/bookmark | Student | Draft/operation scope + mutation ACK → W | Không mất draft/focus; quyền nguồn luôn current | C/tests; browser lần này chỉ page change | P2/007 |
| Đổi hội thoại Tutor | Student | local selectedConv + native history.replaceState; parent query đổi vẫn W | Hiện hội thoại có sẵn ngay; revalidate scope/source riêng | C 008; browser route open, chưa đo switch timing | P2 |
| Tutor gửi câu hỏi mới | Student | Create conversation nếu chưa có → send stream; chunks 20 ms trong mock | Giữ phụ thuộc create→send, stream/stop phản hồi ngay | C; 20 ms là mock streaming, không spinner chung | expected / U latency |
| Stop Tutor / đổi lớp khi stream | Student | local abort/generation, stopRemote, scoped draft | Không nhận chunk cũ; không retry gửi câu hỏi | C/tests; browser stream chưa chạy trong audit | correctness retained |
| Tutor config save | Teacher | Local text, validation, busy mutation rồi reload | Scoped refresh; không bỏ validation/cấm câu hỏi lớp archive | C/tests, B route open | P2/007 |
| Start Practice | Student | Mutation start/resume → route | Busy ngay, không tạo attempt trùng/auto replay | C/tests; B existing attempt, không start mới | expected |
| Practice đổi câu | Student | Native pushState vẫn gây W + StatePanel | Local index không full model reload ngoài nhu cầu quyền nguồn | B: 1 W; 008 | P1 |
| Practice answer autosave/check | Student | Clone/draft/serialize; restored pending có nguy cơ thông báo saved sai | Immediate local input, ACK trung thực, không skip pending | C 013/014?; pending case chưa B | P1 investigation |
| Finish Practice | Student | Queue pending nếu cần → flush → finish | Không rút ngắn bằng bỏ flush/unknown reconciliation | C/tests, B không finish | expected safety |
| Assessment start | Student | Confirm → start → route + self-loader | Busy ngay, same version/attempt authoritative | B trong fixture open | expected |
| Assessment đổi câu | Student | setIndex; không W do đổi câu | Giữ local; không autosubmit hoặc reset timer | C + B attempt open; click next chưa timing | expected |
| Assessment offline→reconcile | Student | Đáp án dirty khiến saving=true dù không write | Tách dirty/saving/reconciling, mở lại explicit save khi an toàn | B 009: nút disabled + 0 write | P1 |
| Assessment save→submit | Student | Có thể enqueue payload đang in-flight, đợi 2 saves | Dedupe snapshot trong controller; vẫn flush đầy đủ trước submit | C + runtime class probe 010 | P2 |
| Assessment timeout/unknown submit | Student | Timer 1Hz + authority reconcile; operationId giữ unknown | Không cache deadline/ACK, không blind retry | C/tests; không end-to-end timeout lần này | P2/013 opportunity |
| Assignment upload/submit | Student | Chuẩn bị tệp riêng → confirm submit; revision + operationId | Không gộp upload thành success submit; giữ reconcile | C/tests, B list route | expected |
| Teacher activities/filter | Teacher | W trước rồi 2 domain list bằng Promise.allSettled | Giữ partial-error; bỏ waterfall nếu summary contract cho phép | B route, C data chain | P2/002 |
| Teacher Practice editor | Teacher | Parent W đầy đủ và authoring load dùng W lại | Một canonical snapshot; draft/version conflicts vẫn rõ | C 002; chưa B editor | P2 |
| Assessment review/publish | Teacher | Có thể persist draft trước review/propose; revision/primary approval | Không parallel hóa save→review/propose/approve | C/tests, chưa B publish | expected safety |
| Grading/score correction | Teacher | Forms + mutation/reload, approval/audit rules | Giữ invalidation evidence/official grade version, không optimistic official score | C/tests, chưa B grading | P2 integration |
| Analytics apply filter | Student/Teacher | Draft filters; apply gọi own port; previous data cùng scope + aria-busy | Phản hồi vùng số liệu, không dùng filter mới để mô tả data cũ | B 1 load/apply, C; slow/error apply cần bổ sung | P2/004 |
| Personal requests create/unknown | Account | Controller khóa retry unknown, explicit refresh list, không suy đoán matching | Giữ hướng dẫn/confirmed/rejected/unknown; không “tối ưu” bằng replay | C/tests; chưa B unknown trong audit này | expected safety |
| Admin data requests/audit | Admin | Own Intelligence load, thêm load khi parent ACK | Stabilize deps; filters local và có empty/error | B list pages, C 004 | P1 |
| Report preview/export/download | Admin | preview → confirmed job → process → download; read-heavy rows | Không bỏ bước snapshot/permission; có pending feedback; profile artifact work | C/tests; B reports route, chưa export file | P2/U |
| Notification select/mark | Account | Select local; controller per-row write/ACK, reconcile khi unknown | Read feedback scoped; giữ state confirmed và actor isolation | C/tests, B route only | expected |
| Notification focus/tab/filter | Account | Focus heading chỉ sau explicit activation; timeout 1s xóa flag | Keyboard/mobile usable; không xem timeout là delay tải | C; focus UX chưa exhaustive B | P3/U |
| Download nguồn/bản sao | Student/Teacher/Account | Source preview/download capability hoặc live unavailable đúng contract | Không cache URL/quyền bị thu hồi, không dựng API mới | C; chưa đo bytes/backend latency | blocked-contract/U |

## D. Detailed Findings

Các finding giữ ID ban đầu; severity khác trạng thái xác minh. P3 của một giả thuyết bị bác không phải bug cần sửa. Đường dẫn dưới đây tương đối với `apps/web`.

### PERF-001 — Workspace không có lifecycle cache giữa các page

- **Severity / status:** P2 · CONFIRMED.
- **Classification:** architectural trade-off / optimization opportunity.
- **File / component:** `src/components/route-screen.tsx:29–59,69; src/components/shell.tsx:18` · RouteScreenInner / PageShell.
- **Evidence:** Mỗi page wrapper tạo RouteScreen; effect gọi W cho protected route. Snapshot chỉ có một key/data trong state component, không shared cache. Warm Back/Forward và tabs vẫn có port calls. Next RSC cache không cache client effect này.
- **Reproduce:** Mở lớp → feed → overview hoặc Back.
- **Root cause:** Route/page lifecycle sở hữu data thay vì resource/session lifecycle; cache absence là chủ ý fail-closed có chi phí.
- **User impact:** Loading và projection chạy lại khi quay về; chưa có số đo backend để quy thành giây production.
- **Proposed fix:** Lập read plan theo route; bỏ load không dùng trước. Sau đó chỉ in-flight dedupe có actor/session/permission scope. Settled cache nhạy cảm phải chờ contract freshness/revocation.
- **Risk / safeguards:** Cache toàn WorkspaceData hoặc giữ previous content bất kỳ có thể lộ nguồn/actor cũ.
- **Regression tests:** Assert scope đổi clear ngay; permission deny/logout invalidates; Back không dùng authority cũ.
- **Worker:** Codex; Argon read-only cache/security review.


### PERF-002 — Parent W vẫn chạy dù feature tự load

- **Severity / status:** P2 · CONFIRMED WITH QUALIFICATIONS.
- **Classification:** architectural trade-off / redundant work.
- **File / component:** `src/components/route-screen.tsx:48–59,73–81; src/features/accounts/index.tsx:20–27; src/features/classroom-admin/index.tsx:15–21; src/features/intelligence/index.tsx:56–73; src/features/assessment/index.tsx:23–30; src/features/assignment/index.tsx:110–115; src/features/learning/views/teacher-practice-editor-view.tsx:48–60; dev/mocks/adapter.ts:525–529,2662–2669` · RouteScreenInner / self-loading feature entries.
- **Evidence:** 40 self-loading routes: 22 non-class không dùng WorkspaceData cho feature/class header; 18 class-scoped có summary ở W và typed domain payload. Chúng phần lớn chạy song song. Ngoài nhóm 40, Practice Editor self-load đi qua dependency snapshot → W, đồng thời parent cũng lấy editor. a.importNew đợi Accounts payload dù ImportNew chỉ cần actorId.
- **Reproduce:** Mở Accounts/Catalog/Analytics/Assignment hoặc editor.
- **Root cause:** Một generic workspace loader áp dụng cho mọi route trong registry, trong khi từng domain đã có loader.
- **User impact:** Thêm computation/state update; summary có thể đến hai lần; không phải hai HTTP cùng payload ở live hiện tại.
- **Proposed fix:** Explicit route load ownership; skip W cho route không dùng. Tích hợp summary từ canonical typed result vào persistent/scoped shell; nếu chưa có cơ chế này giữ load cần thiết. Import picker không tải toàn accounts trước khi cần.
- **Risk / safeguards:** Không được gọi W là permission gate rồi bỏ khi feature còn chưa tự kiểm tra; backend vẫn authoritative, route-role guard giữ nguyên.
- **Regression tests:** Spy loader mount count; route errors/403/empty; same canonical summary; practice draft/revision unchanged.
- **Worker:** Codex logic/ownership; Flash skeleton/layout sau contract nhỏ.


### PERF-003 — Ô search Accounts mất ký tự khi gõ nhanh

- **Severity / status:** P1 · CONFIRMED — BROWSER 3/3.
- **Classification:** interaction bug.
- **File / component:** `src/features/accounts/index.tsx:29–39; src/lib/navigation.ts:3` · AccountList / filter.
- **Evidence:** value={query.get(q)}; onChange → filter → router.replace từng phím, không draft input. Ba lần gõ minh.anh10a1 ở 20 ms/phím đều còn 1; 13 resource/navigation requests/lần; 0 adapter calls. Gõ chậm bằng fill rồi đợi 250 ms từng bước giữ được m/mi/min/minh.
- **Reproduce:** Admin Accounts, focus search, gõ nhanh cả chuỗi.
- **Root cause:** Controlled input phải đợi URL navigation cập nhật nên render từ search cũ ghi đè text vừa nhập.
- **User impact:** Search sai nội dung, khó gõ, route work dư thừa; không phải server search duplicate.
- **Proposed fix:** Local draft search state cập nhật ngay; composition-safe. Đồng bộ URL có debounce/explicit apply hoặc native history theo kiến trúc hiện có; sync Back/Forward và reset page. Nếu tương lai server search, chỉ latest query được apply.
- **Risk / safeguards:** Debounce URL không được trì hoãn input; back/forward/filter deep link phải nhất quán; không sửa allowlist auth-return để giữ filter bừa bãi.
- **Regression tests:** Fast typing/paste/clear/IME; q/group/status/page URL; Back; focus/caret; request count và stale response.
- **Worker:** Codex state/router logic; Flash feedback/labels nếu cần.


### PERF-004 — Raw params dependency làm Analytics/Assignment load thêm

- **Severity / status:** P1 · CONFIRMED — SOURCE + PORT COUNTERS.
- **Classification:** data-loading bug.
- **File / component:** `src/components/route-screen.tsx:29,54–59,81; src/features/intelligence/index.tsx:56–70; src/features/assignment/index.tsx:110–112` · RouteScreenInner / IntelligenceFeature / AssignmentFeature.
- **Evidence:** Mỗi parent render tạo effectiveParams mới. Hai feature dùng cả serialized scope và raw params. Parent setSnapshot không đổi featureKey nhưng đổi params ref; effect cleanup đánh dấu response cũ inactive rồi đọc lại. Dev warm module quan sát 3 feature calls so với 2 strict setup của Assessment.
- **Reproduce:** Feature đã mount trước khi W ACK; hoặc parent render khác với cùng logical params. Cold dynamic import có thể mount sau ACK nên không luôn có extra call.
- **Root cause:** Effect identity không khớp resource identity; serialized scope không ngăn raw object dependency đổi.
- **User impact:** Phí read/compute, busy lại và late response bị bỏ; không có bằng chứng infinite loop.
- **Proposed fix:** Derive canonical primitive resource/filter key và stable effectiveParams; effect capture đúng input từ key. Không bỏ dependencies mà giữ stale closure. Phân biệt path/resource queries với UI-only params.
- **Risk / safeguards:** Sai key có thể dùng dữ liệu lớp/actor/version cũ; abort/dedupe không giải quyết key thiếu scope.
- **Regression tests:** Rerender parent cùng values khác object không thêm load; thay actual resource/filter thêm đúng 1; delayed A→B không apply A.
- **Worker:** Codex; Argon independent review; Flash chỉ scoped loading UI.


### PERF-005 — Feature split coarse nhưng entry/CSS chung vẫn tải nhiều

- **Severity / status:** P2 · MEASURED OPPORTUNITY; REPEATED-CHUNK BUG NOT REPRODUCED.
- **Classification:** bundle/code-splitting trade-off + development overhead.
- **File / component:** `src/features/index.tsx:1–44; src/components/route-screen.tsx:13–14; app/layout.tsx:4–10; next.config.mjs:5–15` · FeatureEntry / RootLayout.
- **Evidence:** 8 dynamic feature modules cấp domain; Document gom reader/library/notes, Assessment/Assignment gồm nhiều role. AuthView và nhiều feature Identity/Classroom/Social/Notification import ở shared entry. Build live báo 152 kB First Load JS cho route mẫu, shared 103 kB. Warm feed không có JS chunk mới. Có 8 CSS request initial shell khoảng 21.3 kB encoded.
- **Reproduce:** First visit module/route; dev cold compile.
- **Root cause:** Code split theo domain, shell nằm trong mỗi page, CSS quan trọng và không liên quan cùng entry.
- **User impact:** Cold parse/compile/load có chi phí; chưa có trace chứng minh bundle là nguyên nhân chính hoặc vượt budget đã duyệt.
- **Proposed fix:** Profile cold/coverage trước. Cân nhắc auth entry tách và split learner/editor/grading; loading fallback có kích thước. Route-specific CSS theo ownership, không xóa selector chỉ vì tên giống legacy. Giữ XLSX lazy import hiện có.
- **Risk / safeguards:** Quá nhiều chunks có thể tạo waterfall, đổi CSS cascade/SSR/hydration; route splitting không được đổi adapter alias.
- **Regression tests:** Cold and warm resource bytes/count; script coverage; hydration errors; visual regression responsive; live canary release scan.
- **Worker:** Codex boundaries/splitting; Flash presentational fallback/CSS.


### PERF-006 — Session restore không chạy lại trên mỗi tab bình thường

- **Severity / status:** P3 · NOT_REPRODUCED AS ROUTE BUG.
- **Classification:** expected auth trade-off / development-only effect replay.
- **File / component:** `app/layout.tsx:11–12; src/components/session-provider.tsx:14–37; src/lib/data/live-identity.ts:16–79; src/lib/api/http.ts:6–41` · SessionProvider / createLiveIdentity.
- **Evidence:** Provider ở root layout, mount effect phụ thuộc stable callbacks. Live restore/refresh giữ single flight + generation/credentialQueue. Browser live shell: initial POST refresh + GET me; 10 nav không thêm auth HTTP. Next local define-env bật StrictMode App Router mặc định trong dev.
- **Reproduce:** Hard reload/provider mount hoặc explicit session.reload có loading toàn màn; navigation bình thường không mount lại provider.
- **Root cause:** Refresh→me có token dependency thật, không phải waterfall có thể bỏ.
- **User impact:** Full-screen session loading chỉ hợp lý khi chưa xác minh được session; không có bằng chứng route đều reload auth.
- **Proposed fix:** Giữ invariants. Nếu thêm cache, gắn session epoch và clear sensitive state ngay auth lost/logout; không dùng persisted access token để làm nhanh.
- **Risk / safeguards:** Memo hóa/caching session sai có thể hiển thị identity cũ; bỏ serialization phá rotated refresh cookie.
- **Regression tests:** Restore concurrency; logout race; 401; warm nav auth request count0; existing live-session tests.
- **Worker:** Codex; không cần Flash hoặc thay provider lúc này.


### PERF-007 — Snapshot-null làm header/tabs/content nhấp nháy

- **Severity / status:** P1 · CONFIRMED — SOURCE + DOM OBSERVATION.
- **Classification:** loading UX bug.
- **File / component:** `src/components/route-screen.tsx:33–46,69–81; src/components/shell.tsx:16–18; src/features/document/views/teacher-library-document-view.tsx:72–82; src/features/document/views/teacher-library-view.tsx:89–115` · RouteScreenInner / ClassHeader / feature loading branches.
- **Evidence:** snapshot key mismatch → data null → summary undefined → ClassHeader returns null. Warm same-class transitions đã quan sát tabsAbsent; các view có early return StatePanel khi !data. Share/revoke/upload ACK gọi reload revision làm cùng việc đó. Link không có explicit application pending feedback trước route commit.
- **Reproduce:** Đổi tab cùng lớp, harmless query hoặc reload sau ACK.
- **Root cause:** Loading model chỉ có có/không snapshot, chưa tách initial load/revalidate/permission revoked hay layout continuity.
- **User impact:** Main content đổi chiều cao, tab mất tạm, cảm giác phải chờ lại toàn trang. Không gán CLS nghiêm trọng từ source; layout shift sau click không đồng nghĩa field CLS.
- **Proposed fix:** Reserve header/content geometry, scoped busy region/pending indication. Preserve only safe non-sensitive same-scope presentation; sensitive source/permission controls phải fail closed khi invalidated. Không giữ previous actor/resource content.
- **Risk / safeguards:** Giữ stale nguồn sau revoke là vi phạm B6/B7/K3; không dùng previous data làm permission decision.
- **Regression tests:** Delayed read/mutation ACK, Cancel, 403/revocation, keyboard focus, 320px; header height ổn định; immediate feedback marker.
- **Worker:** Codex snapshot lifecycle; Flash skeleton/pending/focus with exact file allowlist.


### PERF-008 — UI-only query bị dùng như full workspace key

- **Severity / status:** P1 (Practice); P2 (Reader/Tutor) · CONFIRMED — SOURCE + BROWSER FOR PRACTICE/READER.
- **Classification:** query/data lifecycle coupling bug / qualified trade-off.
- **File / component:** `src/lib/navigation.ts:3; src/components/route-screen.tsx:19–34,39–46; src/features/learning/views/student-practice-attempt-view.tsx:342–346,478–493; src/features/document/views/student-reader-view.tsx:27–43; src/features/tutor/views/student-tutor-workspace.tsx:80–95` · navigateToQuestion / changePage / handleSelectConv.
- **Evidence:** Practice pushState đổi question được useSearchParams nhận, W key đổi; mock W practice branch 2527–2566 không đọc question. Browser 1 đổi câu→1 W. Reader đổi page/version→1 W; Reader mock có page-aware model nên khác Practice. Tutor native history conversationId vẫn cập nhật key parent, không phải local-only tuyệt đối.
- **Reproduce:** Chọn câu Practice khác; Reader next page; Tutor chọn conversation (Tutor chỉ static trace, chưa đo switch).
- **Root cause:** Một key cho resource identity, view position và query UI; router.replace còn có RSC work trong Reader.
- **User impact:** Tải model/đổi loading DOM khi phần lớn data đã có; first pin version có thể đổi feature key theo chủ ý version boundary.
- **Proposed fix:** Route-specific query policy. Practice index dùng local state+URL mà không lấy lại immutable questions chỉ vì index; không dùng snapshot đó làm authority cho nguồn/hints. Reader/Tutor chỉ reuse phần có sẵn theo approved freshness; giữ source revalidation và version/actor/class invalidation. Nếu remote revocation chưa có contract, thiết kế revalidate source hiện hành trước khi bỏ read duy nhất.
- **Risk / safeguards:** Bỏ query khỏi mọi key sẽ làm sai version/permission, nguồn đã revoke vẫn lộ hoặc Back sai vị trí.
- **Regression tests:** Question1→2→Back, focus/unsaved saves remain; page/version actual change; revoke while reading; Tutor stream class switch.
- **Worker:** Codex query/resource policy; Argon permission review; Flash local pending/scroll UI.


### PERF-009 — Assessment reconcile nhầm dirty thành saving

- **Severity / status:** P1 · CONFIRMED — BROWSER OFFLINE REPRODUCTION.
- **Classification:** interaction/state bug.
- **File / component:** `src/features/assessment/index.tsx:59–73; src/features/assessment/answer-save.ts:14–16` · AttemptView.reconcile / saving state.
- **Evidence:** reconcile() setSaving(localAnswers != serverSavedAnswers) sau saver.reconcile(), nhưng không enqueue/flush. UI manual save disabled nếu saving. Browser offline sửa 1/10 → online → reconcile: Đã lưu0/Chưa lưu1, trạng thái Đang lưu…, button disabled; chỉ 1 reconcileSubmission, 0 saveAnswers.
- **Reproduce:** Attempt mở, save offline bị từ chối, online rồi Kiểm tra trạng thái lượt làm.
- **Root cause:** Dirty flag và actual write-in-flight dùng chung saving; reconcile không có state transition đầy đủ.
- **User impact:** Học sinh có cảm giác lưu bị treo và không thể bấm explicit save nếu không sửa thêm đáp án.
- **Proposed fix:** Tách dirty/saving/reconciling/submission-unknown; đối soát revision khi không có active write hoặc đợi đúng flight. IN_PROGRESS dirty phải cho explicit save an toàn; CONFIRMED điều hướng receipt; UNKNOWN vẫn khóa submit replay.
- **Risk / safeguards:** Set saving=false bừa bãi trong lúc còn write sẽ báo ACK sai; không tự gửi lại unknown mutation.
- **Regression tests:** Offline edit→online reconcile→save enabled; active-save reconcile; failed/unknown/confirmed submission; timeout và local draft retained.
- **Worker:** Codex controller/state; Argon review bắt buộc; Flash status/button presentation sau logic.


### PERF-010 — Submit có thể đợi saveAnswers trùng payload

- **Severity / status:** P2 · CONFIRMED — SOURCE + EXECUTED CLASS PROBE.
- **Classification:** duplicate mutation work / interaction latency bug.
- **File / component:** `src/features/assessment/index.tsx:68–70; src/features/assessment/answer-save.ts:10–16` · AttemptView.submit/save / AssessmentAnswerSaver.
- **Evidence:** change enqueue ngay; trước ACK, submit thấy answers khác attempt.savedAnswers nên enqueue cùng snapshot đang write. Saver không so sánh active/queued/ACK payload. Probe chạy class nguyên bản với deferred first ACK thấy 2 writes payload giống nhau, revision2. save() sau reconcile cũng enqueue không kiểm tra equality.
- **Reproduce:** Sửa đáp án rồi submit trước ACK; hoặc explicit save khi server đã có snapshot.
- **Root cause:** Không biết active snapshot identity; so dirty với ACK cũ thay vì state của saver.
- **User impact:** Thêm một round-trip tuần tự trước submit. Chưa có backend để lượng hóa ms. Không phải automatic retry submit.
- **Proposed fix:** Saver theo dõi active/queued/latest ACK fingerprints và revisions; coalesce identical state, giữ edit mới hơn. Flush chờ đúng latest canonical ACK, không bỏ wait.
- **Risk / safeguards:** Dedup sai làm mất edit trong lúc flight; không dùng generic Idempotency-Key cho operation không có contract.
- **Regression tests:** Same in-flight snapshot yields1 write; new edit yields2 distinct writes; error/unknown/reconcile; submit waits; timer expiry saved answers only.
- **Worker:** Codex; Argon read-only regression review.


### PERF-011 — Teacher overview lấy calendar hai lần và có await tuần tự độc lập

- **Severity / status:** P2 · CONFIRMED IN PREVIEW; LIVE COST UNVERIFIED.
- **Classification:** mock projection redundancy / parallelization opportunity.
- **File / component:** `dev/mocks/adapter.ts:421–454,2135–2146; src/features/learning/views/teacher-activities-view.tsx:37–48` · learningCalendar / teacherMetrics / workspace t.overview.
- **Evidence:** t.overview await teacherMetrics (gọi learningCalendar) rồi await makeClassOverview (gọi cùng learningCalendar). Port trace có 2 cặp assessment/assignment calendar mỗi W. learningCalendar từng class dùng await assessment rồi await assignment dù dữ liệu độc lập. TeacherActivities đã Promise.allSettled 2 domain lists, nhưng chỉ chạy sau model W.
- **Reproduce:** Teacher overview/home/calendar hoặc activities.
- **Root cause:** Projection composition chưa share cùng read snapshot; array spread chứa await tuần tự.
- **User impact:** Computation lặp trong preview; thời gian hiện tại nhỏ so dev compile. Không bịa production HTTP endpoints chưa contracted.
- **Proposed fix:** Share một scoped calendar projection trong cùng read operation; parallel các GET độc lập khi có cùng authority/snapshot contract. Không parallel save→review/start→send/preview→confirm.
- **Risk / safeguards:** Mixed revisions/permissions nếu kết hợp cached reads khác scope; không đổi backend contract trong task frontend.
- **Regression tests:** Count same class calendar once/projection; equal event/deadline/grading outputs; partial failure; permission check vẫn chạy.
- **Worker:** Codex mock projection/integration plan; Argon chỉ khi contract thay đổi.


### PERF-012 — Một số ports không nhận AbortSignal

- **Severity / status:** P2 · SOURCE VERIFIED; NETWORK SAVINGS UNVERIFIED.
- **Classification:** read cancellation/dedupe opportunity.
- **File / component:** `src/lib/intelligence.ts:28; src/features/intelligence/index.tsx:65–70; src/features/assignment/index.tsx:112; src/features/assessment/index.tsx:26; src/lib/data/port.ts; src/lib/api/http.ts:8–12,40–41` · typed domain loaders / effect cleanup.
- **Evidence:** W/Accounts/Classroom truyền AbortController. Intelligence/Assignment/Assessment chủ yếu dùng active/generation để bỏ stale response nhưng port không truyền AbortSignal. HTTP client Identity có timeout/signal support, không blanket mutation retry.
- **Reproduce:** Đổi scope/filter nhanh hoặc unmount khi read còn chạy.
- **Root cause:** Logical cancellation khác physical cancellation; method surface chưa hỗ trợ cho các pending live domains.
- **User impact:** Stale response thường bị chặn apply đúng; công việc cũ có thể còn chạy. Chưa có bằng chứng response cũ ghi đè mới trong loader đã xem.
- **Proposed fix:** Trước live integration, thêm optional signal cho READ ports theo adapter contracts; shared dedupe phải có subscriber/ref-count và epoch. Không abort/retry write một cách giả định outcome.
- **Risk / safeguards:** Abort một subscriber có thể hủy nhu cầu subscriber khác; abort network write không chứng minh server rollback.
- **Regression tests:** Delayed A→B scope; last subscriber abort; one subscriber survives; mutation unknown still blocks replay; session generation.
- **Worker:** Codex ports/controllers/tests; Argon async review.


### PERF-013 — Timer lớn, clone mỗi phím, lists/import chưa có stress budget

- **Severity / status:** P2 · SOURCE VERIFIED; BOTTLENECK NOT PROFILED.
- **Classification:** rendering/main-thread optimization opportunity.
- **File / component:** `src/features/assessment/index.tsx:59–73; src/features/learning/views/student-practice-attempt-view.tsx:230–240,532–550; src/features/learning/views/teacher-practice-editor-view.tsx:44–66; src/features/accounts/import-file.ts:7–63; src/features/classroom-admin/presentation/history-panel.tsx:20–82` · AttemptView / draft persistence / file parser / large lists.
- **Evidence:** AttemptView now state cập nhật mỗi giây, cả view tính JSON.stringify/counters lại. Short-answer dispatch save+clone mỗi phím; serialized queue coalesces nhưng nếu ACK nhanh vẫn nhiều writes. Editor sameContent/structuredClone theo content changes. Import đọc toàn file, CSV loop/XLSX parse ở main context, không có bytes/row cap ở readImportFile. Account table đã page-size10; các list/history khác render full array.
- **Reproduce:** Long answer, large question bank/history/CSV; fixture nhỏ chưa đủ chứng minh freeze.
- **Root cause:** State/timer đặt ở component lớn; persistence snapshots toàn map; chưa có dữ liệu stress scale.
- **User impact:** Có khả năng input/render/parse cost; long tasks quan sát chưa được gán stack cho các đoạn này.
- **Proposed fix:** Profile commit/CPU trước. Timer leaf + timeout authority riêng; immediate input/draft, coalesce writes có flush ở blur/check/submit; cap file theo requirement và test workers/virtualization chỉ khi đo cần. Không memo đại trà.
- **Risk / safeguards:** Debounce làm mất final keystroke nếu không flush; giảm timer không được chậm auto-timeout; row cap tự bịa phá nghiệp vụ import.
- **Regression tests:** 10/100/1000 questions; 1k/10k history; CSV byte/row stress; slow CPU; latest answer ACK; timeout, drafts, no lost input.
- **Worker:** Codex state/profiling; Flash leaf/layout/virtualized presentation sau evidence.


### PERF-014 — Practice restored pending và intermediate ACK cần kiểm tra thêm

- **Severity / status:** P1 candidate · REQUIRES_INVESTIGATION — NOT END-TO-END REPRODUCED.
- **Classification:** possible saved-status/ACK correctness bug.
- **File / component:** `src/features/learning/views/student-practice-attempt-view.tsx:145–175,249–286,296–365,581–652; src/features/learning/lib/save-controller.ts:137–161; dev/mocks/adapter.ts:1396–1473` · applyAuthoritativeAttempt / handleCheckAnswer / intermediate save ACK.
- **Evidence:** Restore pending có thể giữ answers mà chưa queue; checkAnswer flush không queue unsent map rồi setSaveStatus(Đã lưu: Vừa xong). Mock checkPracticeAnswer thực sự lưu current question (1469), nên KHÔNG kết luận câu đang check bị mất. Cần case local edit ở câu khác. Intermediate saver ACK cập nhật internal lastSavedAnswers, nhưng view copy ACK chỉ khi global saved; subsequent failure/unmount có thể lưu confirmedAnswers cũ vào draft.
- **Reproduce:** Restore unsent map nhiều câu hoặc save1 ACK→save2 fail/unmount; chưa tái hiện browser đầy đủ.
- **Root cause:** Potential lệch authority snapshot và presentation/draft confirmed state.
- **User impact:** Có nguy cơ thông báo saved quá rộng hoặc draft phải đối soát lại không cần thiết. Không tuyên bố đã mất bài.
- **Proposed fix:** Viết reproducer behavioral trước; lấy latest controller ACK lúc persist/unmount; queue đúng pending trước check khi policy yêu cầu; không đổi các failure semantics dựa trên giả thuyết.
- **Risk / safeguards:** Patch vội có thể tự retry unknown hoặc ghi đè edits mới bằng ACK cũ.
- **Regression tests:** Restored q1/q2 pending→check q1; save1 success/save2 failure; draft confirmed map; source revoke during check; unknown block preserved.
- **Worker:** Codex investigation/tests; Argon độc lập; chưa giao Flash cho đến khi xác minh.


### Findings UI phụ và phản biện kết quả worker

**UX-001 — P1, confirmed encoding issue (ngoài performance):** `src/features/document/views/teacher-library-document-view.tsx:41–55,95,150–165` có các literal tiếng Việt bị mojibake, ví dụ breadcrumb `Quay láº¡i ThÆ° viá»‡n tÃ i liá»‡u`. Source UTF-8 và browser đều xác nhận. Lần chuẩn hóa whitespace trước audit đã đọc file bằng `Get-Content` không chỉ định UTF-8 rồi ghi UTF-8; đây là sai sót xử lý file ở lần bàn giao trước của Codex, không phải API chậm. Lần này giữ audit-only; backlog cần phục hồi từng literal đúng nghĩa từ bản đối chiếu, giữ nguyên logic. Test: source text assertions hữu ích + browser labels/accessible names 320/1440. Owner: Codex khôi phục encoding, Flash rà text/UI, không tự viết lại toàn file.

- Flash nhận diện đúng snapshot-null, search URL coupling, thiếu pending feedback. Codex xác minh bằng source/browser trước khi nhận.
- Không nhận các kết luận “CLS nghiêm trọng”, “focus thoát native modal khi busy”, “double scrollbar do selector” như bug đã chứng minh. Flash không chạy browser; class-name/declaration collision không đủ để kết luận computed layout lỗi. Accounts/share dialog được đo tại 4 widths không root horizontal overflow; share Escape đóng và focus quay về button. Chưa chứng minh mọi modal/busy state đều đạt.
- Native showModal focus vào nút Đóng đã quan sát; đó là focus placement hiện tại, chưa đủ kết luận mất keystroke. Notification focus heading chỉ sau explicit activation; `setTimeout(1000)` xóa activation flag, **không trì hoãn tải thông báo**.
- Argon đúng về raw params và extra parent work, nhưng “deterministic double on every mount” được thu hẹp: cold dynamic import có thể mount sau parent ACK; dev còn StrictMode. Không gọi mọi cặp W/domain là duplicate cùng payload.
- Teacher archived analytics có divergence static giữa mock workspace allowlist (`dev/mocks/adapter.ts:2058–2061`) và Intelligence (`dev/mocks/intelligence.ts:39–40`): summary có thể mất trong shell dù analytics có limited-history payload. Đây là candidate consistency issue, chưa browser reproduce; cần dùng cùng current permission projection khi làm 002, không tự thêm quyền mới.

## E. Optimization Roadmap và cache architecture được review

Ưu tiên tác động + bằng chứng, sau đó rủi ro và chi phí. Không có task nào dưới đây đã triển khai trong lần audit này.

| Thứ tự / Task | Scope / ownership | Acceptance chính | Rủi ro / cost |
|---|---|---|---|
| 1 · OPT-01 / PERF-009 | Codex: `src/features/assessment/index.tsx`, `answer-save.ts`, assessment tests. Argon review read-only. Flash chỉ status/button markup trong allowlist sau logic | Offline→online→reconcile dirty không kẹt; active write không báo false saved; UNKNOWN không replay; timeout/receipt đúng | State phức tạp, impact cao; M |
| 2 · OPT-02 / PERF-003 | Codex: `features/accounts/index.tsx`, focused navigation/input tests. Flash: account CSS/pending labels nếu cần | 3 repeated fast typing/paste/IME giữ đủ text; Back/URL/group/status/page khớp; không navigation từng phím không cần thiết | Scope nhỏ, chắc chắn cao; S–M |
| 3 · OPT-03 / PERF-004 | Codex: `components/route-screen.tsx`, Intelligence/Assignment entry effects + tests | Cùng logical params không load thêm sau parent ACK; đổi scope load đúng; stale response không apply | Shared route key dễ regression; M |
| 4 · OPT-04 / PERF-008 | Codex: route query policy, Practice/Reader/Tutor query handling; Argon permission audit. Flash: focus/loading only | Practice index local không reload toàn model ngoài nhu cầu authority; version/class/actor đổi vẫn clear; revoke-source semantics giữ | Quyền nguồn/live contract còn thiếu; M–L |
| 5 · OPT-05 / PERF-010 | Codex: saver + AttemptView submit/save/tests; Argon review | Identical in-flight snapshot1 write; newer edit vẫn được save và await trước submit | Không được bỏ flush hoặc replay unknown; M |
| 6 · OPT-06 / PERF-002/007 | Codex load plan/canonical summary; Flash skeleton/pending/responsive với exact file allowlist | Non-consuming route W0; không summary/permission divergence; header geometry/focus ổn định; sensitive data hidden after invalidation | 40+ routes; chia theo domain, không một invocation “fix all”; L |
| 7 · OPT-07 / PERF-014? | Codex reproducer Practice ACK/draft; Argon audit | Chứng minh hoặc bác candidate trước sửa, không false saved toàn map | Correctness phức tạp; M |
| 8 · OPT-08 / PERF-011/012 | Codex in-flight read lifecycle/projection; Argon cache approval | Dedupe GET scope đúng; permissions/auth invalidation; không generic write retry | Không settled sensitive cache khi thiếu contracts; M |
| 9 · OPT-09 / PERF-005/013 | Codex CPU/React profiling, code splitting. Flash route/loading/CSS leaf | Có before/after trace chứng minh benefit; test chậm CPU/large fixtures; live gate không leak mock | Chưa có bottleneck attribution; M–L |
| Parallel small follow-up · UX-001 | Codex literal encoding; Flash text/accessible labels review | Tiếng Việt đúng, logic không đổi, source hash phần không liên quan giữ nguyên | Rủi ro thấp; S |

### Cache/dedupe proposal sau Argon review

**Bước đầu đề xuất: không cài thư viện mới.** Trước cache, sửa identity/query/loader ownership để tránh che bug bằng caching. Một read coalescer nhỏ chỉ dùng chung promise đang chạy, xóa sau settle (settled TTL=0) có thể đủ cho scope hiện tại.

Key phải gồm `dataMode + sessionEpoch + actorId + schoolId + sorted roles + permissionEpoch + operation + canonical resource/filter params`. DataMode sống trong build nhưng vẫn đưa vào namespace/harness để không ghép mock/live. Chỉ canonicalize key thuộc đúng query policy; không bỏ version/attempt/filter quyết định dữ liệu.

Mỗi subscriber có cancel riêng; hủy underlying read khi không còn subscriber. Response thuộc session/permission epoch cũ không được publish dù HTTP đã xong. Logout/auth lost/actor-school-role đổi xóa sensitive entries và chặn late writes. Local revoke/enrollment/archive/restore/assignment/grading mutations invalidate các projection liên quan sau state outcome hợp lệ; unknown outcome giữ trạng thái cần đối soát, không giả định quyền hoặc dữ liệu đã đổi thành công.

**Local epoch không giải quyết remote revocation.** Chưa có contract sự kiện quyền/grant/membership hoặc freshness được duyệt, không thể hứa “thu hồi tức thì” chỉ bằng TTL hoặc SWR. Không settled-cache source text, private chat, permission decisions, signed download URLs, mutable attempts, deadline/remaining time, receipts/official grades chưa xác nhận. Các nguồn/hints/notes quote phải bị che khi authority bị mất hoặc chưa xác minh được. Published question version có thể bất biến; quyền mở nguồn gắn vào nó vẫn thay đổi riêng.

Prefetch: Next Link prefetch RSC/chunk không chạy client workspace effect trước navigation. Có thể prefetch code cần thiết sau intent nếu measurements chứng minh benefit, không tự khởi động attempt/mutation hay prefetch private resources không có quyền. Khi hợp đồng live hoàn thiện, settled cache chỉ áp dụng resource có policy được phê duyệt; UI stale phải thể hiện đúng scope, không dùng stale data để authorize write.

| Lựa chọn | Lợi ích | Chi phí / giới hạn | Khuyến nghị |
|---|---|---|---|
| Read coalescer tự xây (in-flight only) | Không thêm dependency, coalesce cùng GET, kiểm soát session/permission epoch | Tự viết subscription/cancel/error/lifetime tests; không giải quyết stale reuse | Thử sau OPT-01/02/03/06 với surface nhỏ |
| SWR | Query dedupe/revalidation/previous-data API có sẵn | Phải gắn key/provider theo session, tắt default retry/focus behavior ở sensitive flows theo policy; vẫn cần invalidation backend | Chỉ cân nhắc khi nhiều live read đã contracted; không cài trong audit |
| TanStack Query | Query lifecycle/cancellation/invalidation/devtools phong phú | Thêm provider/dependency, migration nhiều loader, queryFn phải consume signal; stale/gc/refetch/retry defaults không phải permission policy | Cân nhắc khi workload live lớn cần quản lý cache; cần proof-of-concept/size budget |

SWR/TanStack Query không tự ngăn cross-user leaks hoặc biết grant bị thu hồi; cả ba phương án vẫn cần cùng security safeguards. Không dùng library chỉ để giảm số dòng useEffect.

## F. Before/After Benchmark Plan

Mọi target dưới đây là **mục tiêu đề xuất, chưa đạt/chưa nghiệm thu**. Ưu tiên invariant về số công việc và tính đúng đắn trước millisecond.

| Kịch bản | Baseline audit | Target đề xuất / phép xác nhận |
|---|---|---|
| Fast Account search | 3/3 còn `1` thay `minh.anh10a1`; 13 resources/navigation/trial; 0 data calls | 100% giữ text/caret/composition; local filter feedback ≤100 ms trên cùng máy; URL update không quá1/lần query commit, không RSC từng phím nếu chỉ local |
| Parent rerender cùng params | Intelligence/Assignment có extra feature call sau W ACK | 0 extra call do ref identity; production1 logical read per required resource; dev strict replay phân loại riêng |
| Practice đổi câu | 1 W cho local question query | 0 full immutable-question reload chỉ vì index; vẫn authority revalidate nguồn theo policy; không mất pending save/draft |
| Reader page | 1 W + router query navigation | Khi approved payload có đủ trang, không fetch lại cùng bytes; version/permission đổi vẫn hard invalidate; chưa đặt0 read mặc định cho nguồn nhạy cảm |
| Official reconcile dirty | Saving=true/no write, save button locked | Sau read xong: dirty=true, saving=false khi không write, explicit save enabled nếu authority/online cho phép; UNKNOWN vẫn không retry |
| Submit identical active answer | 2 identical saves trước submit trong class probe | 1 same-snapshot save; newer snapshots vẫn lưu đủ; submit không nhanh bằng bỏ ACK |
| Same-class warm tab | Preview med content upper bounds khoảng 279–327 ms; feedback136–161 ms theo role/action | Pending/feedback ≤100 ms; giữ bố cục; content median ≤300 ms là budget local đề xuất sau đo apples-to-apples. Backend latency thật tách riêng |
| Cold route/module | Dev compile single sample2.34–4.07s; live full domain chưa đo | So dev cold/warm riêng, không dùng dev compile làm SLA; production với service thật cần baseline mới |
| Timer/render/large data | Chưa có React commit/CPU attribution | Profile render commit, long tasks và input latency 10/100/1000 questions, 1k/10k rows; chỉ đặt budget component sau trace |
| Bundle | Next reported sample152kB First Load JS, shared103kB; initial CSS8 resources~21.3kB encoded | So cold bytes/cache-hit chunk count, no increase ngoài lý do; split phải chứng minh net latency, không hứa giảm% trước prototype |

Protocol sau sửa: cố định Chrome/máy/viewport/data/clock/backend delay, đóng competing builds và ghi resource cache state. Dùng sample warm tối thiểu20 mỗi action cho ổn định; cold tối thiểu5 context/cache-cold với server production sẵn build. Chỉ báo p95 khi số mẫu đủ và n công khai (đề xuất ≥100/action); theo dõi field INP qua instrumentation được duyệt để có dữ liệu người dùng thật. Không cộng nhiều steps thành một “click time”.

Đo riêng uninstrumented baseline và instrumented call counts; current timings có overhead instrumentation/polling. Sau patch, dùng Event Timing + rAF/screenshot marker xác nhận paint, CDP tracing/React Profiler cho commit/CPU attribution nếu có. Record dropped/aborted requests, duplicate identity dựa trên method+scope+params+purpose; không gộp CSS/RSC/GET khác tài nguyên.

Permission regression bắt buộc cho mọi tối ưu: actor A→logout→B, role/school đổi, revoke source khi viewer/tutor mở, archive/enrollment ended, unknown mutation, old response sau epoch mới, private chat, immutable exam version/timer/resume, grade correction/evidence invalidation. Backend vẫn quyết định quyền; không tự thêm API/event contract.

## G. Test Evidence và verification status

### Commands thực sự chạy

| Lệnh / công cụ | Nơi chạy | Kết quả / giới hạn |
|---|---|---|
| `agy --version`, `agy models`, `codex --version`, `node --version` | Repo root, read-only environment | AGY1.4.3; hai model yêu cầu available; Codex CLI0.163.0; Node22.17.0 |
| `npm run check` | **Source thật `apps/web`** | PASS exit0: boundaries, TypeScript, **196 tests passed / 0 fail**. Không phải performance browser test |
| `python inventory.py` / `inventory.py after` | External scratch | 71 definitions,72 pages; 257 SHA256 file hashes,0 changed/removed |
| Direct AGY argv `--model gemini-4-argon-high --mode=plan --output-format json` task PERF-A01 | Repo cwd, prompt read-only/no-shell/no-Git | SUCCESS; route/data/cache architecture; Codex independently verified |
| Direct AGY argv `--model gemini-3.8-flash-high --mode=plan --output-format json` task PERF-F01 | Repo cwd, read-only | SUCCESS; UI/navigation/search/dialog audit; unsupported claims filtered, không coi worker là browser QA |
| Direct AGY argv Argon task PERF-A02 | Repo cwd, read-only | SUCCESS; attempt/save architecture, findings cross-checked; 014 remains investigation |
| `node scripts/dev-mock.mjs --hostname 127.0.0.1 --port 4186` | Source-linked harness | Development mock preview only. Không đổi nguồn/production gate |
| `$env:NEXT_PUBLIC_DATA_MODE='live'; npm run build` | Source-linked harness, byte-identical route copy | PASS exit0: boundary, Next compile/type/page generation, release canary scan. CSS autoprefixer start/end warnings có thật; không chặn build. **Không chạy lại build trong source thật để tránh generated file/HMR tranh chấp** |
| `node node_modules/next/dist/bin/next start --hostname 127.0.0.1 --port 4187` | Harness live `.next` | PASS ready; chỉ dùng cho browser shell experiment, không deploy |
| Python Playwright `browser-audit.py` Student / Lecturer Admin | Isolated headless Chrome, mock preview | Main Student valid27 actions trước harness timeout; staff run38 actions complete. Teacher documents timeout trước đó do selector bắt loader trong dialog ẩn, đã sửa harness và chạy lại. Không là infinite product loading |
| `interaction-probes.py` | Mock preview | Final run15 checks,0 failures; accounts/share geometry4 widths; Practice/Reader query; mojibake; Escape |
| `interaction-probes.py search analytics` | Mock preview | Final8 checks,0 harness failures;3 lost-text trials và1 actual Analytics apply read |
| `interaction-probes.py assessment` | Mock preview |1 probe,0 harness failures; confirmed saving-state bug. Chỉ tạo/edit/reconcile fixture attempt; không submit hoặc destructive live mutation |
| `assessment-save-probe.ts` qua installed `tsx` | External scratch, imports original class | PASS reproducer:2 identical writes,revision2. Các lỗi loader-path ESM của harness trước đó đã sửa; không sửa saver |
| `production-browser.py` | Live build + isolated browser Identity stub |10 nav complete; initial refresh/me2 HTTP,0 thêm trên nav; domain unavailable giữ nguyên; không chứng nhận backend |

Các lần thử harness thất bại được ghi riêng và không gắn PASS cho product flow: shared-output session loss, junction-app 404, selector sai role tab, wait URL nhầm query `next`, selector bắt hidden loader, ESM probe path và npm forwarding CLI flags. Final numbers chỉ lấy run có điều kiện hợp lệ. `browser-metrics.json` có Teacher partial failure; chỉ các Student action đã hoàn tất trong file đó được tổng hợp, Teacher dùng run `browser-lecturer-admin.json`.

### Evidence files

Tất cả raw evidence/harness ở `D:/app/web/2010/artifacts/lumi-perf-audit` (ngoài source sản phẩm):

- `source-before.json`, `source-after.json`, `routes.json`: fingerprint/inventory.
- `browser-metrics.json`, `browser-lecturer-admin.json`: action timing upper bounds, port trace, resource entries, observer entries. `browser-exploratory.json`: cold exploratory và đoạn readiness bị loại, không tự dùng toàn file làm baseline.
- `interaction-probes.json`, `interaction-search-analytics.json`, `interaction-assessment.json`: exact reproduction results.
- `production-metrics.json`, `bundle-metrics.json`, `build-audit.log`: live shell/bundle/build evidence (build log UTF-16 do PowerShell redirection).
- `assessment-reconcile-locked.png`, `practice-question.png`, `account-dialog.png`, `production-unavailable.png`, role-final screenshots: snapshot hỗ trợ, không chứng nhận mọi route responsive.
- `PERF-A01.md`, `PERF-F01.md`, `PERF-A02.md`: bounded task contracts. AGY raw `*.private.json` logs giữ cục bộ, không đưa vào product/report repository. Không có credentials `.env` trong prompts.

### Scope thực sự được browser kiểm tra

Student: login/home, classes, overview/feed/documents/reader/tutor/practice/assessments/assignments/calendar/progress, notes, notifications, global calendar; existing Practice attempt question change; official open Assessment detail/start/offline/reconcile. Teacher: login/home/classes, overview/feed/documents/tutor/activities/calendar/analytics, personal library/document detail, share dialog open/Escape. Admin: Accounts search/detail dialog, Catalog/Homerooms/Classes/Data Requests/Audit/Reports/Import picker, basic Back/Forward.

Các route khác trong matrix là **static audit**, có thể có existing unit coverage, không gọi là đã browser-pass. Share/revoke/upload/retry processing, Tutor send/stop/conversation-switch timing, import confirm, roster/transfer/archive, editor publish, grading/approval, actual download/export, deadline expiry và các races cross-user chưa được browser thực hiện đầy đủ trong lần audit này. Test cũ được đọc không thay bằng bằng chứng browser mới.

### Những giới hạn chưa xác minh

Không có Core/service thật, production school dataset, durable persistence/email/AI/file extraction/download backend. Không có field INP/p95, React commit trace, CPU-stack attribution hay leak soak test. Chrome headless local và tiny fixtures không đại diện mobile low-end/network trường học. Geometry4 widths chỉ cho Accounts/share dialog, không toàn71 routes. Một vài form/list chỉ source audit. PERF-014 và archived analytics consistency cần reproduction riêng trước sửa. Những mục này là giới hạn bằng chứng, không được đánh dấu pass.

### Trả lời sáu câu hỏi nghiệm thu

1. **Chậm do đâu?** Dev cold compilation; generic workspace lifecycle không reuse giữa page; object identity làm read thêm; query UI bị gắn full read; loading thay toàn vùng; riêng Assessment có state kẹt và save trùng. Backend thật chưa đo.
2. **Có bug thật không?** Có: search mất text, extra load do params, Practice query reload, Assessment saving lock và duplicate save. Không cache/serialization auth, dependency create→send/save→submit là lựa chọn cần bảo vệ, không mặc định bug.
3. **Sửa trước?** Không P0 confirmed; ưu tiên OPT-01/02/03/04 cho P1, rồi saver dedupe, shared loader/layout, cache/profiling. UX-001 encoding là lỗi riêng cần xử lý nhỏ sau khi được giao triển khai.
4. **Tối ưu tới đâu?** Có cơ sở loại công việc cụ thể (extra feature read, local query full read, duplicate same snapshot), giữ đủ text và tránh loading flash. Chưa đủ số liệu để hứa nhanh hơn bao nhiêu% hoặc backend nhanh dưới ngưỡng nào.
5. **Không phá nghiệp vụ thế nào?** Giữ current backend authority, actor/session/permission isolation, immutable versions/timer/ACK/unknown handling; không settled-cache nguồn/attempt nhạy cảm thiếu policy; mỗi task có focused regression + check/live build/browser tests.
6. **Phân công?** Codex sở hữu route/query/state/ports/cache/save logic và tests; Flash chỉ bounded pending/skeleton/focus/CSS sau logic contract; Argon read-only audit/review cho attempt concurrency/cache/permission. Một feature cohesive/invocation, không parallel writes cùng file, không model/provider changes.

**Bàn giao:** báo cáo này là kết quả audit và kế hoạch triển khai. Mã sản phẩm chưa được sửa; không có commit/push/PR hoặc thao tác Git trong audit.
