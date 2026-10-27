# Lumi — Performance fixes and acceptance

Ngày kiểm tra: 21/10/2026. Phạm vi: `apps/web`, source có sẵn tại máy. Baseline: [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md). Báo cáo audit giữ nguyên số liệu trước sửa; tài liệu này ghi trạng thái sau triển khai.

## 1. Kết quả

Đã sửa các bug đã xác minh về search, identity của loader, đọc workspace dư, query điều khiển vị trí, autosave/đối soát Assessment, ACK và bản nháp Practice, loading header và encoding trang tài liệu. Không thêm cache dữ liệu nhạy cảm giữa route, không tự retry mutation unknown. Không thao tác Git, đổi backend, business rules, API HTTP, dependencies, model/provider hoặc release gates.

`npm run check`: **PASS — 211/211 test**, tăng 15 regression so với baseline 196. `NEXT_PUBLIC_DATA_MODE=live npm run build`: **PASS**; boundary check, TypeScript, Next build và release fixture scan đều đạt. Browser kiểm tra bằng Google Chrome cài sẵn, Python Playwright có sẵn; không cài package.

AGY Flash tạo ba component/CSS trình bày trong allowlist. Codex viết logic, ports, adapters, tích hợp và kiểm thử. Argon review read-only phát hiện các rủi ro Assessment; Codex xác minh và sửa, vòng review cuối trả `pass`, không còn finding chặn trong phần mã đã review. Kết quả worker không thay thế test/browser QA.

## 2. Trạng thái từng finding

| ID | Trạng thái sau sửa | Thay đổi / quyết định | Bằng chứng và giới hạn |
|---|---|---|---|
| PERF-001 | Architectural trade-off, giữ fresh read khi quay lại route | Loại read dư và query refetch; không thêm settled cache/SWR tự xây dựng | Chưa có hợp đồng invalidation/revocation để chứng nhận cache nguồn hoặc quyền. Back sang resource khác vẫn đọc authority. Không hứa mọi route quay lại đều không loading. |
| PERF-002 | FIXED | 41 route do feature sở hữu read không gọi thêm parent workspace. Class header lấy cùng projection domain đã xác thực; ImportNew không cần Accounts.load | Browser self-loader còn đúng tầng domain; unit test metadata PRIMARY/ASSISTING, membership và role denial. Practice Editor vẫn có read projection bên trong authoring, không có parent read thứ hai. |
| PERF-003 | FIXED | Local input tức thì; đồng bộ URL sau 200ms bằng history API được Next hỗ trợ; giữ IME và Back/Forward | Gõ `minh.anh10a1` 20ms/phím: 3/3 đủ chuỗi, giữ focus, 0 navigation/request. Test composition và history đạt. |
| PERF-004 | FIXED | Canonical params + primitive resource scope; stable params cho Intelligence/Assignment; cleanup read bằng AbortController | Dev analytics/assignment từ 3 domain load + 2 W thành 2 domain load + 0 W. Hai invocation còn lại là StrictMode effect replay, không phải hai tầng production request. |
| PERF-005 | IMPLEMENTED, hiệu quả bundle có giới hạn | FeatureEntry registry được tải động sau auth; CSS feature do owner import; giữ các dynamic domain imports và XLSX lazy import | Next route First Load JS 152 kB → 130 kB, shared 103 kB giữ nguyên. Đây là metric build, không phải toàn bộ JS cuối cùng sau khi tải feature hay cam kết tăng tốc tương ứng. Không split thêm hàng loạt khi chưa có CPU/coverage trace. |
| PERF-006 | NOT_REPRODUCED, không sửa auth lifecycle | Giữ root SessionProvider, refresh single-flight, token và logout semantics | Production shell browser: initial refresh + me; 10 navigation không thêm auth HTTP. Regression auth/session/privacy giữ nguyên. |
| PERF-007 | FIXED trong shared shell | NavigationLink dùng native useLinkStatus; header skeleton giữ vùng bố cục khi chưa có quyền/dữ liệu; không hiển thị summary của actor/resource khác | Keyboard Enter chuyển tab đạt; skeleton không gây body overflow ở 1440/768/390/320px. Error/permission denial gỡ metadata đã mất authority. Không giữ stale nguồn sau revoke để làm loading đẹp hơn. |
| PERF-008 | FIXED Practice/Reader; Tutor giữ resource read có lý do | Question position không là resource key. Reader dùng trang đã có trong version model; nếu thiếu trang hoặc query sai vẫn load, có fallback cả history. Version và conversationId vẫn là resource key | Chuyển câu/trang đã có: 0 W. Partial Reader: 1 read khi cần trang mới; query ngoài phạm vi vẫn lỗi. Tutor workspace thực sự chọn hội thoại từ conversationId nên không bỏ read đó. |
| PERF-009 | FIXED | Tách dirty/pending khỏi write đang chạy; read reconciliation không giả làm autosave; serialize read/write barrier | Offline edit → online → reconcile: không write, nút lưu dùng được; explicit save ACK đúng. Browser còn kiểm tra clock reanchor và server conflict. |
| PERF-010 | FIXED | Dedupe active/confirmed answers, latest snapshot queue, canonical answer equality; submit flush không lưu lại cùng payload | Browser giữ autosave chậm rồi submit: 1 save + 1 submit; ACK loss sau dispatch giữ operationId, read lại receipt, không submit lần hai. Unit A→B→A, unknown, dispose và key order đạt. |
| PERF-011 | FIXED trong preview projection | Hai calendar reads độc lập chạy song song; TeacherOverview chia sẻ kết quả calendar trong đúng một operation; metrics/overview song song | Dev teacher overview từ 4 assessment calendar + 4 assignment calendar còn 2 + 2 (StrictMode). Không thêm cache tồn tại qua actor/route. Không suy ra latency backend thật từ adapter preview. |
| PERF-012 | FIXED lifecycle hiện có | Optional AbortSignal ở Assessment/Assignment/Intelligence/Practice authoring; feature cleanup, generation/actor guards, pre/post-abort checks | Abort regression đạt; obsolete read không publish snapshot. Các domain live chưa có hợp đồng vẫn unavailable. Không tuyên bố đã hủy HTTP của API chưa tồn tại hoặc mọi computation đang chạy đồng bộ. |
| PERF-013 | FIXED các điểm có nguyên nhân rõ; stress opportunities giữ mở | Đồng hồ thi cập nhật ở leaf, dùng monotonic elapsed từ server anchor; short-answer autosave coalesce 200ms, explicit flush bỏ chờ; giảm clone dư trong Practice controller | Unit timer/reanchor/delay/flush/dispose đạt. Không có React commit/CPU stack trace trên dataset production; chưa có cơ sở thêm virtualization, memo đại trà hay giới hạn import tùy ý. |
| PERF-014 | CONFIRMED rồi FIXED | ACK trung gian được publish/persist ngay, kể cả write sau lỗi; restored pending snapshot phải qua flushAnswers trước check/finish; không false saved toàn map | Regression intermediate ACK→unknown và restored draft barrier đạt. Unknown giữ block tới read đối soát + thao tác tường minh; không background retry. |
| UX-001 | FIXED | Khôi phục chuỗi tiếng Việt trang Teacher Library Document | Browser không còn mojibake; share dialog, focus/Escape và 4 viewport đạt. |

Không coi PERF-001, PERF-006, dev cold compilation hoặc các stress hypotheses chưa đo là bug để “sửa” bằng bỏ kiểm tra quyền. Không có finding P0 chưa xử lý được xác nhận trong phạm vi vòng này.

## 3. Chi tiết triển khai và safeguards

### Route, loader và phân quyền

- `route-load-plan.ts` tách identity tài nguyên khỏi vị trí UI; path params thắng query an toàn. Reader version và Tutor conversationId không bị bỏ khỏi identity.
- Snapshot và class-header projection gắn user ID, roles, school, route và resource. Actor/resource đổi thì dữ liệu trước không còn được chọn để render. `ClassSummaryProvider` chỉ nhận summary cùng lớp đã qua domain loader; không dùng summary làm bằng chứng cấp quyền mutation.
- Bỏ parent workspace trên các route tự load, giữ nguyên guard role ở RouteScreen và authorization ở domain adapter. Không cache source, không share in-flight/settled data giữa user. Logout/session invalidation tiếp tục xóa volatile drafts.
- Intelligence/Assignment không refetch do object params mới cùng giá trị. Read lỗi gỡ projection không còn được xác thực; không fallback mock trong live.
- Read chỉ nhận thêm optional cancellation argument tại frontend port; không khai báo API/backend mới. Abort ngăn response cũ publish, không đổi mutation behavior.

### Assessment

- Saver serialize revision, coalesce snapshot, dedupe active/confirmed payload, giữ failed/unknown tới authority reconciliation. Lỗi lưu không bị xóa chỉ vì người dùng gõ tiếp.
- Pending short answer đợi tối đa debounce 200ms khi nhàn; explicit save/submit flush ngay. Không giả thành công trước ACK. Read reconciliation dừng timer chưa gửi và chờ write đang chạy hoàn tất.
- Đồng hồ 1Hz nằm trong component riêng; serverNow được neo vào performance.now. Cập nhật endsAt/server clock sau read có thể mở lại bài nếu server xác nhận còn thời gian. Read hết giờ lỗi vẫn fail closed; nút kiểm tra trạng thái cho phép thử read lại, không tự nộp lặp.
- Unknown submit giữ operationId từ trước dispatch, kể cả lỗi mạng chưa được wrap. Chỉ known rejected outcome mới bỏ operationId. Read xác nhận receipt không gửi mutation thứ hai.
- Nếu bản nháp khác bản lưu mới hơn, giữ local draft và khóa ghi cho tới người dùng chọn server hoặc chọn bản nháp để lưu ở bước sau. Không tự ghi đè remote. Chọn một bản chưa phải lưu/nộp. Bản nháp vẫn chỉ sống trong session memory, đúng mục tiêu phục hồi hiện có.
- Equality bỏ phụ thuộc thứ tự key/object và thứ tự option trong multiple choice; vẫn giữ nguyên nội dung short answer. Server tiếp tục là authority thời hạn, phiên bản và kết quả.

### Practice và Reader

- Practice onAcknowledged cập nhật last confirmed answers/time sau mỗi ACK, không chỉ khi toàn bộ queue rỗng. Error/unknown của write tiếp theo không mất ACK đã xác nhận.
- Explicit check/finish gọi flushAnswers với latest snapshot, bao gồm bản nháp pending được khôi phục. Không queue lại unknown ngầm. Badge saved chỉ khi map được xác nhận.
- Reader không ép pin version ngầm mỗi lần đổi trang; version có trong URL vẫn được tôn trọng. Trang đã trả trong model không cần read. Partial model hoặc URL sai vẫn qua adapter để xác nhận, bao gồm Back/Forward; không có vòng lặp tải trang thiếu.

### UI và code ownership

Flash task `OPT-UI-01` chỉ tạo `navigation-link.tsx`, `class-header-placeholder.tsx`, `navigation-feedback.css`. Codex kiểm tra và tích hợp, chỉnh spinner chỉ chạy khi pending, giữ reduced motion và native link semantics. Không đổi design system toàn cục. Feature CSS vẫn import ở owner tương ứng.

Argon `OPT-ARGON-01` không có review hợp lệ do file-read bị từ chối; không tính là pass. `OPT-ARGON-02` nhận source inline, trả needs_changes; Codex sửa các finding đã xác minh và bổ sung test. `OPT-ARGON-03` review source inline, verdict pass, no findings; worker không chạy test và không sửa source. Không dùng bridge vì bridge buộc Git trái phạm vi; direct CLI dùng đúng model/mode, task contract và allowlist, không đổi cấu hình toàn cục.

## 4. Số liệu trước / sau

Môi trường: cùng máy Windows, Chrome headless, mock Next development preview ở cổng riêng, không throttle. Mỗi sample warm là một thao tác; n=5 cho mỗi cặp role/route. Thời gian content là **upper bound tại thời điểm harness quan sát readiness**, không phải React commit time hay INP. Cold compile một mẫu không dùng để kết luận cải thiện. Các vòng không random/interleave, còn nhiễu hệ thống; không báo p95 hoặc phần trăm tăng tốc chung.

| Phép đo | Trước | Sau | Diễn giải |
|---|---|---|---|
| Gõ nhanh Accounts, 3 lần | Chuỗi cuối chỉ `1`; 13 navigation/resource requests mỗi lần | Chuỗi đủ; 0 request mỗi lần | Bug rõ ràng đã hết trong phép thử |
| Student progress / assignment first visit, dev | 2 W + 3 domain load | 0 W + 2 domain load | Loại tầng dư và extra refetch do identity; StrictMode vẫn replay |
| Teacher analytics first visit, dev | 2 W + 3 Intelligence.load | 0 W + 2 Intelligence.load | Cùng kết luận về counts |
| Admin catalog first visit, dev | 2 W + 2 Classroom.load | 0 W + 2 Classroom.load | Domain read vẫn giữ quyền |
| Reader resident page / Practice question | 1 W cho mỗi đổi vị trí | 0 W | Không đổi resource nên không đọc lại |
| Teacher overview calendar reads, dev | 4 + 4 | 2 + 2 | Một calendar projection mỗi operation |
| Student overview warm upper bound, median (range), n=5 | 326.7ms (210.3–429.6) | 223.5ms (200.7–301.8) | Quan sát local, không phải KPI production |
| Student feed warm upper bound, median (range), n=5 | 279.3ms (197.3–323.6) | 253.5ms (210.0–338.3) | Có nhiễu, không khẳng định cải thiện mọi sample |
| Teacher overview warm upper bound, median, n=5 | 302.3ms | 256.6ms | Loại projection trùng; không quy toàn bộ chênh lệch cho code |
| Teacher feed warm upper bound, median, n=5 | 308.8ms | 291.8ms | Route không được thêm settled cache |
| Next route First Load JS | 152kB | 130kB | Deferred registry; không phải tổng eventual authenticated JS |
| Live production shell, 10 nav, content upper-bound median | 99.05ms | 104.6ms | **Không chứng minh shell content nhanh hơn**; giữ semantic loading/auth |
| Live shell observed feedback median, 10 nav | 12.15ms | 2.2ms | Marker quan sát DOM/frame; không gọi là field INP |
| Live shell auth HTTP | refresh + me, sau đó 0 | refresh + me, sau đó 0 | Session lifecycle không bị hồi quy |

Live production browser dùng **Identity contract stub ở browser**, domain khác vẫn unavailable từ live adapter. Đây là smoke shell/auth lifecycle, không phải benchmark backend thật, không phải mock production build.

## 5. Kiểm thử và nghiệm thu

| Gate / journey | Kết quả thực tế |
|---|---|
| Baseline npm run check | PASS, 196/196 |
| Final npm run check tại apps/web | PASS, 211/211, boundaries + tsc + tests |
| Final NEXT_PUBLIC_DATA_MODE=live npm run build tại apps/web | PASS, Next build và release-policy fixture scan |
| Focused saver/lifecycle regressions | PASS; có trong full suite 211 |
| Three-role browser navigation | 65 thao tác, 32 route IDs trong broad navigation script, 0 pageerror |
| Interaction probes | 18 quan sát, 0 failure: search, Practice position, Reader position, document text/share dialog, analytics apply, offline reconcile |
| Adverse journeys | IME/Back/Forward; offline save; expiry reanchor; remote draft conflict; duplicate flush + unknown submit đều PASS |
| Reader partial/invalid/history probe | PASS: out-of-range không mở nội dung; trang thiếu đọc một lần; history khớp trang |
| Loading skeleton + keyboard | PASS: Enter chuyển tab, placeholder rồi 9 student tabs; body overflow 0 tại 1440/768/390/320px |
| Library/share và Accounts responsive | Body overflow 0 ở 4 viewport; Escape đóng dialog và trả focus về button |
| Live production shell smoke | 10 navigation, 2 initial Identity HTTP, 0 additional auth HTTP; domain unavailable đúng live boundary |
| Final Argon read-only review | PASS trong đoạn mã được review; không phải browser QA |

Có hai lỗi harness đã sửa rồi chạy lại: locator Reader bị encoding khi tạo script qua Windows stdin (không phải lỗi text sản phẩm), và npm/PowerShell nuốt option start hostname/port. Reader được chạy lại riêng đạt; production server được gọi trực tiếp bằng Next CLI và chạy smoke đạt. Không đánh dấu các lần thử lỗi đó là pass.

Bằng chứng cục bộ: `D:/app/web/2010/artifacts/lumi-perf-fixes/`:

- `baseline.json`, `changed-files.json`: snapshot SHA-256 và phạm vi file, không dùng Git.
- `final-check.log`, `final-live-build.log`: quality gates cuối.
- `browser-metrics.json`: 65 thao tác và calls/resources/DOM observation.
- `interaction-probes.json`: 18 probe sau sửa.
- `adverse-journeys.json`, `acceptance-journeys.json`, `reader-fallback.json`: fault injection, keyboard, geometry; file acceptance còn ghi lần locator lỗi, reader-fallback ghi lần sửa harness và pass.
- `production-metrics.json`: shell live với Identity stub; `production-browser.py` ghi rõ stub boundary.
- Các task contracts OPT-UI-01/OPT-ARGON-02/OPT-ARGON-03; private AGY logs giữ ở scratch, không đưa vào product source.

Baseline có tại `D:/app/web/2010/artifacts/lumi-perf-audit/`, gồm browser-metrics.json và browser-lecturer-admin.json. Các số cũ không bị ghi đè.

## 6. File thay đổi

22 file đã có được chỉnh, 9 file mới (7 product helpers/components, 2 test files), cộng báo cáo này. Những file ngoài danh sách source/config đã chụp vẫn giữ hash trong baseline. package.json, lockfile, next.config.mjs, tsconfig.json, business rules và skill không bị chỉnh để lách gate.

### File đã có

- `app/layout.tsx`
- `src/components/route-screen.tsx`
- `src/components/shell.tsx`
- `src/lib/assessment.ts`
- `src/lib/assignment.ts`
- `src/lib/intelligence.ts`
- `src/lib/practice-authoring.ts`
- `src/features/accounts/index.tsx`
- `src/features/assessment/answer-save.ts`
- `src/features/assessment/index.tsx`
- `src/features/assignment/index.tsx`
- `src/features/intelligence/index.tsx`
- `src/features/document/views/student-reader-view.tsx`
- `src/features/document/views/teacher-library-document-view.tsx`
- `src/features/learning/lib/save-controller.ts`
- `src/features/learning/views/student-practice-attempt-view.tsx`
- `src/features/learning/views/teacher-practice-editor-view.tsx`
- `dev/mocks/adapter.ts`
- `dev/mocks/assessment.ts`
- `dev/mocks/assignment.ts`
- `dev/mocks/intelligence.ts`
- `dev/mocks/practice-authoring.ts`

### File mới

- `src/components/class-header-placeholder.tsx`
- `src/components/class-summary-context.tsx`
- `src/components/navigation-feedback.css`
- `src/components/navigation-link.tsx`
- `src/lib/route-load-plan.ts`
- `src/features/assessment/answer-equality.ts`
- `src/features/assessment/countdown.tsx`
- `tests/assessment-save-regression.test.ts`
- `tests/performance-lifecycle.test.ts`

## 7. Giới hạn còn lại

- Chưa có backend/domain contracts và dataset production đủ để nghiệm thu caching/invalidation, tải tệp/AI/điểm thật end-to-end. Các phần pending-contract giữ unavailable trung thực; preview không chứng nhận production backend.
- Không kiểm tra toàn bộ 71 route bằng browser trong vòng này. Mọi route đã được inventory/static audit ở baseline; vòng sửa dùng broad 32-route navigation và các journey tập trung bổ sung, cùng regression các feature liên quan.
- Chưa có field INP/p95, React Profiler commit trace, memory soak, low-end mobile/network throttle hay stress budget thực cho CSV/XLSX/list lớn. Không thêm library data fetching, virtualization hoặc bulk import limits khi chưa có chứng cứ/lựa chọn nghiệp vụ.
- Dev cold compilation còn là overhead bình thường; các cold samples sau sửa có thể chậm hơn vì compile khác module. Warm content không được giữ qua permission invalidation để làm số đẹp.
- Shared class header được giữ bằng placeholder trong lúc xác minh, không giữ nguyên các tab có quyền cũ. Fresh read vẫn cần thiết ở các route khác tài nguyên.

Phạm vi các bug đã xác minh trong audit đã được xử lý và qua kiểm tra nêu trên. Các trade-off/hypothesis chưa được chứng minh được ghi tách biệt, không coi là đã đạt KPI hay đã kiểm thử live backend.


## 8. Bổ sung — cold compilation trong dev:mock (21/10/2026)

Sau vòng sửa phía trên, người dùng cung cấp log Webpack: `/login` compile 12.6s / GET 13.312s; các route mở lại GET khoảng 94–280ms. Các số GET là thời gian server dev, không phải toàn bộ interaction latency. Lần đầu route phải compile là phần lớn khác biệt trong log này.

Đã đổi `scripts/dev-mock.mjs` để `npm run dev:mock` dùng `--turbopack` của Next 15.5.12. Có `npm run dev:mock:webpack` giữ compiler cũ để đối chiếu khi cần. Không đổi phiên bản package hay build production. `next.config.mjs` bổ sung `turbopack.root` là app web và `turbopack.resolveAlias`; alias chọn cùng adapter theo mode như Webpack. Cả hai vẫn tách `.next-preview`/`.next` và cấm mock production.

Đây là thay đổi **bổ sung sau** danh sách 31 source/test files ở mục 6: `next.config.mjs`, `scripts/dev-mock.mjs`, `package.json`, `docs/FRONTEND.md`, `tests/integration-boundary.test.ts`, cùng cập nhật báo cáo này. Không sửa dependencies/lockfile, backend, rules, skills hoặc model settings. Không có thao tác Git.

Đo kiểm soát bằng hai bản sao source với output/cache rỗng riêng; Chrome headless, một lượt cho mỗi compiler, không throttle. `/login` tới form-ready: Webpack **9781ms**, Turbopack **4703ms**. Đây chỉ là một cặp mẫu, không phải median/p95 hoặc cam kết giảm 52% trên mọi máy. Các route lớp khác vẫn cần compile lần đầu, có sample Turbo cải thiện ít hoặc chậm hơn; warm overview/feed trong lượt này không chứng minh Turbo nhanh hơn. Không biến một phép đo cold login thành KPI tổng thể.

Hai QA copies dùng `turbopack.root=D:/app` để chứa node_modules junction; source thật dùng root `apps/web` vì node_modules nằm trực tiếp bên trong. Không chạy hai compiler cùng output của người dùng, không đọc/copy `.env.local`. Log source và số liệu: `D:/app/web/2010/artifacts/lumi-cold-start/cold-comparison.json`. Test boundaries `Webpack and Turbopack resolve the same mode-specific adapter and keep output isolation` được thêm vào full suite.

- `npm run check`: PASS, **212/212**.
- `NEXT_PUBLIC_DATA_MODE=live npm run build`: PASS, bao gồm fixture release scan.
- Mock Turbopack cold navigation: đăng nhập và 12 lần chuyển route Student, 0 pageerror, 0 API request trong flow mock; runner mới khởi động hiển thị `Next.js 15.5.12 (Turbopack)`.
- Browser smoke bổ sung ghi ở `bundler-smoke.json`; chỉ kết quả thực pass trong file này được tính nghiệm thu. Live smoke là negative transport test khi không có Core cấu hình, không phải live backend end-to-end.

Cách áp dụng: dừng dev server đang mở bằng Ctrl+C rồi chạy lại `npm run dev:mock`. Dòng Next phải có `(Turbopack)`. Cấu hình này giảm phần compiler cold startup; không loại hết chi phí lần mở đầu hoặc giữ compiled routes qua mọi lần restart. Đổi compiler cần dừng server cũ trước. Các lệnh production/live giữ nguyên.

Tham chiếu chính thức: [Turbopack Next 15](https://nextjs.org/docs/15/app/api-reference/turbopack), [cấu hình alias/root](https://nextjs.org/docs/15/app/api-reference/config/next-config-js/turbopack). Turbopack không chạy hàm webpack(), nên thêm flag đơn lẻ khi chưa cấu hình alias là không đủ.


Nghiệm thu bundler bổ sung đã xong: `bundler-smoke.json` có 3 role mock PASS (Student canonical header, Teacher share dialog, Admin rapid search + CSV import), 0 pageerror. Negative live test ban đầu chờ 1600ms trong lúc API dev còn compile nên assertion đến quá sớm; harness được đổi sang chờ response thật. `bundler-live-smoke.json`: PASS, POST `/api/v1/auth/login` nhận 503 khi không cấu hình Core, không có fixture login. Hai kết quả này không chứng nhận backend production. Chỉ các server QA ở 4188/4189 được dọn sau kiểm tra; server người dùng không bị dừng.
