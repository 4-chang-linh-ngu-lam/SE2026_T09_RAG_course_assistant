# Lumi frontend — nghiệm thu bổ sung 22/10/2026

## Phạm vi và nguồn chuẩn

Làm việc trực tiếp với source cục bộ trong `apps/web`; không thực hiện thao tác Git. Đọc root/web AGENTS, skill Lumi orchestrator, FRONTEND.md, BUSINESS_RULES và integration registry. Bộ Stitch hiện hành gồm 104 canvas (kể cả modal, responsive và reference board), ánh xạ thành 71 product routes; không dùng các bộ canvas lịch sử làm bản chốt.

Các script `.qa` ở `D:/app/web/2010/.qa` dẫn tới bộ tham chiếu chuẩn tại `D:/app/cnpm/frontend/artifacts`. Đợt này đối chiếu trực tiếp HTML/SHA các mẫu SH_C01-home, SH_C02-overview, base-fef514df và base-37714fad với screen registry; bốn SHA khớp. Tái sử dụng shell và pattern đã có, giữ dữ liệu runtime và phân quyền cao hơn sample thiết kế.

## Lỗi đã xác minh và sửa

| ID | Mức | Xác minh | Giải pháp | Nghiệm thu |
|---|---|---|---|---|
| FIN-301 | P1 | 4 trang Admin chi tiết báo không tìm thấy dù ID hợp lệ: params được serialize thành mảng entries rồi dùng như object | Dùng canonicalParams để ổn định tham chiếu và giữ object classId/homeroomId | Roster, settings, enrollment, lifecycle mở đúng lớp; browser sửa/đối chiếu scope |
| FIN-302 | P1 | Lịch sử bản nộp trên correction/approval của giáo viên mở route chỉ dành cho học sinh | Href theo audience của trang, giáo viên mở grading cùng class/assignment/submission; học sinh giữ own-result route | Route-guard regression + click-through browser; không mở rộng quyền |
| FIN-303 | P1 | Teacher Home tự hiện 14 bài chờ chấm khi thiếu stats, đồng thời cộng roster có thể trùng học sinh | Giữ metrics chưa biết là null/Chưa có dữ liệu; bảo toàn 0 và tổng hợp do adapter cung cấp | 2 regression tests về missing/zero/authoritative metrics; 2 tests riêng cho scope active của dashboard |
| FIN-304 | P2 | Bộ lọc lớp dùng tablist/tab thiếu semantics panel/keyboard; count=0 bị truthiness | Nhóm native button với aria-pressed, giữ xử lý filter; hiển thị số 0 đúng | Browser keyboard và responsive |
| FIN-305 | P2 | Ô tìm kiếm tài liệu và Practice thiếu accessible name | Bổ sung hai aria-label, giữ nguyên state/handlers | Labels browser qua 4 viewport trên màn liên quan |
| FIN-306 | P2 | Student Home lặp Hạn: Hạn nộp và Teacher Home lặp Phòng Phòng | Hiển thị dueDetail/location do adapter trả về, bỏ prefix Hạn/Phòng thừa | Browser assertion nội dung |
| FIN-307 | P2 | Card archived thiếu nhãn và trỏ tới overview đang bị adapter khóa | CTA sang bài đã nộp hợp lệ; ẩn feed/calendar đã bị khóa và loại thảo luận/lịch dạy của lớp archived khỏi mục công việc hiện hành. Overview có presentation readOnly cho view-model archived, không nới adapter | Admin archive → SPA đổi sang giáo viên được phân công → mở bài đã nộp; backend/preview guard giữ nguyên |
| FIN-308 | P2 | Tab Tiến độ trên 390px nằm ở x=1011..1110 trong viewport nav x=16..374, scrollLeft=0 | Reveal tab hiện hành chỉ trong thanh cuộn, theo route/class/resize, không cuộn dọc trang và không ép người dùng sau manual scroll | 2 regression tests + browser Student/Teacher tại 4 viewport |
| FIN-309 | P3 | Thông báo từ chối lịch sử lớp đang hoạt động bị mất dấu | Sửa duy nhất nội dung error copy trong mock adapter | Browser kiểm tra tiếng Việt và guard vẫn fail closed |
| FIN-310 | P3 | `.empty-card` trong Classroom không có CSS nên chữ sát viền trên ảnh cuối | Thêm stylesheet scoped cho 5 container Classroom, padding 16px, reset margin đoạn văn; giữ nguyên các card khác | AGY UI-306 + browser đo padding/overflow, tổng quan/lịch sử và 4 viewport |

Trạng thái xác minh: FIN-301…FIN-310 đều **CONFIRMED** trong source hoặc browser và đã được sửa như bảng trên. REV-201/REV-202 là **ALREADY_FIXED** ở baseline, được review và kiểm tra hồi quy lại trong đợt này.

REV-201/REV-202 đã có trong baseline đầu đợt này: giữ khóa unknown outcome, fresh-read đối soát, chống stale response, draft scoped actor/resource/revision và baseline sạch/bẩn. Argon review lại PASS. Browser xác nhận hủy lưu trữ, xác nhận archive/restore, reset lý do ở revision mới, Cancel điều hướng và khôi phục draft cùng revision. Khi chuyển sang giáo viên được phân công, dashboard không còn quảng bá trả lời thảo luận hoặc lịch dạy của lớp vừa lưu trữ; vẫn mở được bài đã nộp theo guard hiện có. Fault injection unknown outcome vẫn dựa vào unit tests/review; chưa có live Classroom API để nghiệm thu lỗi mạng thực.

## Phân công AI và giới hạn worker

- Codex: xác minh nguyên nhân, sửa params/href/số liệu/visibility hook, tích hợp, tests, browser QA và release gates.
- AGY Gemini 3.8 Flash High UI-302: sinh 7 thay thế được review và tích hợp trong 4 component lớp/trang chủ; UI-303: sinh 2 nhãn search, được review và tích hợp. UI-306: sinh CSS cho trạng thái rỗng, Codex review và tích hợp trong đúng stylesheet/entry Classroom cho phép.
- AGY UI-301 và UI-304 trả output rỗng hoặc bị từ chối đọc; không tính SUCCESS rỗng là đạt. Codex hoàn thiện trực tiếp phần archive theo quyền đã được người dùng cho phép khi Gemini không hoàn tất.
- AGY Gemini 4 Argon High REVIEW-305: read-only, PASS, không có finding còn mở trong phạm vi load/lifecycle/draft đã cung cấp. Worker không chạy tests.
- Không dùng bridge có bước Git trong đợt không-Git này; gọi CLI trực tiếp với task contract riêng. Chỉ truyền những đoạn source UI/logic cần thiết, không cấp toàn repository, env hoặc backend. Không đổi model/provider/approval settings toàn cục.

## Kiểm thử thực tế

- Baseline: `npm run check` PASS, **218/218**.
- Cuối đợt: `npm run check` PASS (exit 0), **226/226**, gồm boundary, TypeScript và test; 0 failed/skipped.
- `NEXT_PUBLIC_DATA_MODE=live npm run build`: PASS (exit 0), có release fixture scan. Không dùng mock production build.
- Source có **72 page.tsx**, gồm 71 route sản phẩm và root redirect.
- Chrome headless qua Playwright Python: **68/68 route seed** có nội dung ready ở 1440/390px; 0 pageerror, không có input không được gắn nhãn trong main ở những state đã kiểm tra, không tràn document theo chiều ngang.
- Ba route còn lại được mở bằng resource phát sinh qua UI: `a.import` từ CSV thật, `t.correctionApproval` từ đề xuất vừa tạo và `s.examAttempt` từ lượt làm bắt đầu thật trong mock. Kết hợp đủ **71/71 route ID**, không dùng ID giả để báo thành công.
- Focused journeys (`browser-focused.py admin learning presentation classroom-empty` + negative guard): **214/214 assertion**, gồm quản trị, import, link giáo viên, đề xuất/chờ phê duyệt, bắt đầu Assessment, giữ câu trả lời/lỗi lưu khi offline, nhóm filter/menu bằng keyboard và lớp lưu trữ. Các màn focused được kiểm tra tại 1440/768/390/320px như evidence.
- CSS trạng thái rỗng được đo bằng `getComputedStyle`: padding tối thiểu 16px và không tràn nội dung ở những khung rỗng thực sự hiển thị; không chỉ kiểm tra class có tồn tại.
- Tab Progress/Analytics được kiểm tra trực tiếp sau resize: tab hiện hành nằm trong nav viewport, main scrollTop không đổi; thanh tab vẫn cho manual scroll.
- Harness focused ghi nhận 0 request API nghiệp vụ trong mock QA. Không phải bằng chứng email/AI/file extraction/database hay backend production đã hoạt động.

Source src/app được băm trước/sau vòng route scan; không đổi trong lượt scan. Sau đó CTA archive và mục công việc hiện hành trên Teacher Home được hoàn thiện, CSS trạng thái rỗng cũng được bổ sung trong module Classroom, rồi kiểm tra lại toàn bộ focused journeys trên bản cuối; error copy trong mock được kiểm tra riêng bằng guard âm tính. Full check/build cuối chạy trên source đã hoàn thiện này. Những lượt harness ban đầu chờ loading chưa đúng và lượt cổng 3000 bị ngừng được loại khỏi kết quả pass. Server QA riêng 4179 được dùng cho vòng cuối. Không gán sự cố cổng 3000 cho product khi chưa có bằng chứng.

## Ma trận route thực tế

Browser role bên dưới là vai trò đã dùng trong smoke; shared routes không ngầm được xem là đã thử mọi vai trò/trạng thái. Ready smoke không thay cho nghiệm thu mọi mutation hoặc mọi canvas state.

| Route ID | Path | Browser role | Evidence | Live readiness |
|---|---|---|---|---|
| auth.login | `/login` | Public | Ready smoke PASS | Contracted; real Core unverified |
| auth.activate | `/activate` | Public | Ready smoke PASS | Contracted; real Core unverified |
| auth.invitation | `/staff/invitation` | Public | Ready smoke PASS | Pending domain contract / unavailable live |
| auth.recover | `/recover` | Public | Ready smoke PASS | Contracted; real Core unverified |
| auth.reset | `/reset-password` | Public | Ready smoke PASS | Contracted; real Core unverified |
| s.home | `/student` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.classes | `/student/classes` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.overview | `/student/classes/:classId/overview` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.feed | `/student/classes/:classId/feed` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.documents | `/student/classes/:classId/documents` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.reader | `/student/classes/:classId/documents/:documentId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.tutor | `/student/classes/:classId/tutor` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.practice | `/student/classes/:classId/practice` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.practiceAttempt | `/student/classes/:classId/practice/:practiceId/attempts/:attemptId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.practiceResult | `/student/classes/:classId/practice/:practiceId/attempts/:attemptId/result` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.assessments | `/student/classes/:classId/assessments` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.assessment | `/student/classes/:classId/assessments/:assessmentId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.examAttempt | `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId` | Student | UI-created resource + focused PASS | Pending domain contract / unavailable live |
| s.receipt | `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/receipt` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.examResult | `/student/classes/:classId/assessments/:assessmentId/attempts/:attemptId/result` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.assignments | `/student/classes/:classId/assignments` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.assignment | `/student/classes/:classId/assignments/:assignmentId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.calendar | `/student/classes/:classId/calendar` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.progress | `/student/classes/:classId/progress` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.notes | `/student/notes` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.history | `/student/history/classes/:classId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| s.historyResult | `/student/history/results/:resultId` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| account.profile | `/account` | Student | Ready smoke PASS | Contracted; real Core unverified |
| account.requests | `/account/data-requests` | Student | Ready smoke PASS | Self list/create contracted; copy/review pending |
| account.notifications | `/notifications` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| account.calendar | `/calendar` | Student | Ready smoke PASS | Pending domain contract / unavailable live |
| t.home | `/teacher` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.classes | `/teacher/classes` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.overview | `/teacher/classes/:classId/overview` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.feed | `/teacher/classes/:classId/feed` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.calendar | `/teacher/classes/:classId/calendar` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.documents | `/teacher/classes/:classId/documents` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.tutor | `/teacher/classes/:classId/tutor` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.activities | `/teacher/classes/:classId/activities` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.practiceEditor | `/teacher/classes/:classId/practice/:practiceId/edit` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.assessmentEditor | `/teacher/classes/:classId/assessments/:assessmentId/edit` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.assessmentApproval | `/teacher/classes/:classId/assessments/:assessmentId/review` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.assignmentEditor | `/teacher/classes/:classId/assignments/:assignmentId/edit` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.gradingQueue | `/teacher/classes/:classId/grading` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.assignmentGrading | `/teacher/classes/:classId/assignments/:assignmentId/submissions/:submissionId/grade` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.examGrading | `/teacher/classes/:classId/assessments/:assessmentId/attempts/:attemptId/grade` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.correction | `/teacher/classes/:classId/appeals/:appealId` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.correctionApproval | `/teacher/classes/:classId/grade-proposals/:proposalId/review` | Teacher | UI-created resource + focused PASS | Pending domain contract / unavailable live |
| t.analytics | `/teacher/classes/:classId/analytics` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.studentAnalytics | `/teacher/classes/:classId/analytics/students/:studentId` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.library | `/teacher/library` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| t.libraryDocument | `/teacher/library/:documentId` | Teacher | Ready smoke PASS | Pending domain contract / unavailable live |
| a.accounts | `/admin/accounts` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.account | `/admin/accounts/:userId` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.legacy | `/admin/accounts/legacy` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.newStudent | `/admin/accounts/students/new` | Admin | Ready smoke PASS | Contracted; real Core unverified |
| a.staffInvite | `/admin/accounts/staff/invitations` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.importNew | `/admin/imports/new` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.import | `/admin/imports/:importId` | Admin | UI-created resource + focused PASS | Pending domain contract / unavailable live |
| a.catalog | `/admin/catalog` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.homerooms | `/admin/homerooms` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.homeroom | `/admin/homerooms/:homeroomId` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.classes | `/admin/classes` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.newClass | `/admin/classes/new` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.classSettings | `/admin/classes/:classId/settings` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.enrollment | `/admin/classes/:classId/enrollment` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.lifecycle | `/admin/classes/:classId/lifecycle` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.dataRequests | `/admin/data-requests` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.audit | `/admin/audit` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.reports | `/admin/reports` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |
| a.exports | `/admin/reports/exports` | Admin | Ready smoke PASS | Pending domain contract / unavailable live |

## File thay đổi trong đợt này

- `dev/mocks/adapter.ts`
- `src/components/class-tab-visibility.ts`
- `src/components/shell.tsx`
- `src/features/assignment/index.tsx`
- `src/features/classroom-admin/index.tsx`
- `src/features/classroom/empty-states.css`
- `src/features/classroom/index.tsx`
- `src/features/classroom/student-classes.tsx`
- `src/features/classroom/student-home.tsx`
- `src/features/classroom/teacher-classes.tsx`
- `src/features/classroom/teacher-home.tsx`
- `src/features/classroom/teacher-overview.tsx`
- `src/features/document/views/student-class-documents-view.tsx`
- `src/features/learning/views/student-practice-list-view.tsx`
- `src/lib/assignment.ts`
- `src/lib/classroom-presentation.ts`
- `tests/assignment-navigation.test.ts`
- `tests/class-tab-visibility.test.ts`
- `tests/classroom-presentation.test.ts`

Tài liệu bàn giao được cập nhật thêm: `FRONTEND_COMPLETION.md`, `docs/FRONTEND.md`, root `docs/ai/FRONTEND_ORCHESTRATION.md`. Mock adapter chỉ đổi một error-copy mất dấu; không đổi fixture rows, state hoặc guard. Không thay thin page wrappers, API contract, integration registry, build config, backend, migrations, package/lockfile hoặc skill.

## Evidence có thể chạy/đọc lại

Thư mục: `D:/app/web/2010/.qa/lumi-finish/`.

- `final-check.log`, `final-build.log`: lệnh/gates thực tế.
- `routes-all.json`, `browser-routes.py`: route smoke và source-unchanged flag.
- `focused-admin-learning-presentation-classroom-empty.json`, `browser-focused.py`: từng assertion/route/viewport và lỗi; ba route tạo mới nằm ở đây.
- `class-tabs-before.json`, tabObservations trong focused report: bằng chứng tab bị khuất và sau sửa.
- `design-evidence.json`: đường dẫn/hash của nguồn Stitch chuẩn.
- `UI-302-integration.json`, `UI-303-integration.json`, `UI-306-integration.json`, `REVIEW-305-result.json`: output được chấp nhận; output rỗng không được tính nghiệm thu.
- Các ảnh `*-final-1440.png`, `*-final-320.png`: minh họa màn focused. Ảnh chụp từ mock có thể có preview bar.

## Còn phụ thuộc contract hoặc chưa chứng nhận

- Identity/provisioning/self-request có client contract nhưng chưa xác nhận với Core/database/email thật trong đợt này.
- Classroom, Social, Notification, Administration/import, Document, AI, Learning và Intelligence còn pending-contract theo registry hiện hành. UI/port/mock có hành vi, live phải trả unavailable trung thực đến khi có contract được phê duyệt; không tự phát minh endpoint hoặc fallback fixture.
- Self-request copy download, Admin data review/copy processing cũng pending-contract. Live file storage/extraction, AI stream, quyền/điểm bền vững, thông báo và report production chưa được chứng nhận.
- Không tuyên bố đã nghiệm thu pixel mọi 104 canvas, mọi role/state trên 71 route, screen reader thực, mọi browser/thiết bị, field INP/p95, React commit profile hoặc tải production lớn. Browser kiểm tra rộng 1440/390 và focused 4 viewport; không suy rộng sang các phép đo chưa chạy.
- Nhánh archived trong Teacher Overview chỉ được source-review vì adapter hiện tại chặn route overview của lớp archived. Browser đã nghiệm thu card archived và đích bài đã nộp hợp lệ; không tính nhánh overview đó là browser-pass.
- Unknown mutation outcome cần kiểm tra tiếp trên hợp đồng/backend thật khi khả dụng; không tự replay mutation để làm nhanh hơn.

File ownership: AGY Flash chỉ đề xuất UI trong các file ghi ở UI-302/303/306; Codex áp dụng thay đổi, sở hữu các helper/logic/test và chốt kiểm thử. File API/adapter live/permission rules không thay đổi.

Các lỗi frontend đã xác minh trong đợt này được xử lý và qua các gates nêu trên. Các phụ thuộc live còn thiếu được giữ rõ trong UI/integration registry, tách khỏi nghiệm thu mock.
