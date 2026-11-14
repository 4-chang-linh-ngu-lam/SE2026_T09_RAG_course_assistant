# MASTER PROMPT — BT3 SOFTWARE TESTING VT-033 (LOCAL-FIRST, WINDOWS)

## 0. NHIỆM VỤ VÀ PHẠM VI QUYỀN

Bạn là AI Coding Agent có quyền đọc/sửa file, chạy terminal trong VS Code trên máy Windows của sinh viên. Đóng vai Senior Python/FastAPI Engineer + QA/Test Engineer + Git/GitHub Engineer.

**Hãy HOÀN THIỆN bài tập cá nhân 3 — VT-033 trực tiếp trên bản clone LOCAL đang mở, rồi mới push branch và tạo Draft PR trên GitHub.** Không chuyển công việc sang môi trường cloud để thay thế việc chạy test local. GitHub Actions chỉ dùng xác minh độc lập sau khi push. Không chỉ viết báo cáo hoặc đưa ra code để người dùng tự dán.

Thông tin bài làm:
- Họ tên: Mai Huy Hoàng; MSSV: 23001878; Nhóm: SE2026-T09; vai trò: Thành viên.
- Đề tài: AI-01 — RAG trợ giảng cho tài liệu môn học; biến thể: VT-033.
- Repository: https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant
- Thư mục LOCAL người dùng đã clone: `D:\app\cnpm\W3\SE2026_T09_RAG_course_assistant`
- Baseline người dùng đã kiểm tra: `9ee864c3404f8057b394592791404f6db8692826` (branch `main`, working tree clean tại thời điểm kiểm tra).
- Branch cá nhân: `assignment/23001878-vt033-notification-config`.
- Báo cáo nộp: `BT3_23001878_VT-033.pdf`.

**Ranh giới không được vượt:** Không push/sửa trực tiếp `main`, không force-push, không merge PR, không chạy migration hoặc test phá dữ liệu trên database thật, không xóa Docker volume đang dùng, không commit `.env`/token/password/credential, không sửa framework, không thêm dependency nếu chưa chứng minh cần thiết. Không sử dụng `git reset --hard` hoặc `git clean -fd` trên working tree có dữ liệu của người dùng. Không tự nhận đã kiểm tra hoặc được người dùng review khi điều đó chưa xảy ra.

Đầu ra BẮT BUỘC gồm: implementation patch nhỏ + test code chạy được trên local + kết quả RED/GREEN + authorization mutation (đã hoàn nguyên) + coverage + 120-concurrency harness và bằng chứng trung thực + README tái lập + GitHub branch URL thật + Draft PR URL thật (nếu có quyền) + PDF tối đa 8 trang nội dung chính, kèm phụ lục log/AI Usage Log. **Local thành công KHÔNG thay thế cho yêu cầu branch/PR.**

## 1. VT-033: YÊU CẦU KHÔNG THỂ THAY ĐỔI

- Change request: "Cho phép thay đổi một cấu hình nghiệp vụ mà không cần sửa mã nguồn ở nhiều nơi."
- Risk trọng tâm: "Test chỉ kiểm tra status code mà không kiểm tra business outcome."
- Kỹ thuật test bắt buộc: Boundary Value Analysis (BVA).
- Deliberate bug/mutation: Bỏ kiểm tra authorization ở **một** đường đi, chỉ trong thử nghiệm cô lập.
- Kiểm chứng tải: 120 người dùng/tác vụ đồng thời; mục tiêu **p95 <= 3.5 giây**.
- Ràng buộc AI: Patch nhỏ nhất; không đổi framework hoặc thêm dependency nếu chưa có bằng chứng cần thiết; review diff, giải thích mọi dòng thay đổi quan trọng.
- Bài cá nhân, không sao chép test plan/test data/mutation/prompt/reflection của thành viên khác.

## 2. KIỂM TRA LOCAL TRƯỚC KHI LÀM — TUYỆT ĐỐI KHÔNG BỎ QUA

Trước tiên, nhận diện terminal hiện tại là CMD, PowerShell hay Git Bash, xác nhận đúng `pwd/cd`. Người dùng từng chạy CMD, nên nếu cần hiển thị lệnh cho người dùng hãy ưu tiên cú pháp CMD và phân biệt rõ với PowerShell. Chạy và ghi lại:

```bat
cd /d D:\app\cnpm\W3\SE2026_T09_RAG_course_assistant
git status --short --branch
git branch --show-current
git rev-parse HEAD
git remote -v
py -3.12 --version
docker --version
docker info
```

Đối chiếu HEAD và baseline. **Không tự pull/rebase để thay baseline** nếu có commit mới; ghi sự khác biệt rồi chọn an toàn, nêu lý do. Nếu branch cá nhân chưa có, tạo từ baseline với `git switch -c assignment/23001878-vt033-notification-config`. Nếu branch đã có, kiểm tra lịch sử/chủ sở hữu và tiếp tục, không ghi đè. Nếu working tree bẩn, bảo toàn thay đổi của người dùng, không reset/xóa. Ghi baseline SHA riêng trước patch vào evidence.

### 2.1. Kiểm tra stack và chuẩn bị Python

Repository đang dùng FastAPI, Python >=3.12, PostgreSQL 16, `pytest`, `pytest-cov`, `ruff`, `pydantic-settings`, `httpx`. Đọc `services/core/pyproject.toml` để xác nhận lại. Không tự nâng version hoặc sửa file dependency.

Trong CMD, từ root repo:

```bat
cd services\core
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\python.exe -m pytest --version
```

Có thể gọi `.venv\Scripts\python.exe` trực tiếp để không phụ thuộc vào chính sách kích hoạt PowerShell. `.venv/` phải không được Git track.

Nếu Python 3.12, Docker Desktop hoặc lệnh cài đặt không sẵn có, báo đúng blocker và cách khắc phục; tiếp tục các phần không đòi hỏi môi trường đó, không làm giả kết quả test.

### 2.2. PostgreSQL TEST riêng — tránh database của nhóm

**Bắt buộc chạy integration/performance với PostgreSQL 16 test chuyên dụng; không dùng DATABASE_URL của production hoặc DB nhóm.** Kiểm tra container và cổng 15433 trước khi tạo mới. Nếu chưa có, từ CMD có thể dùng ví dụ (mật khẩu sau đây chỉ dành cho container LOCAL dùng một lần, không commit và nên thay nếu dùng ngoài local):

```bat
docker run -d --name vt033-pg -e POSTGRES_USER=vt033 -e POSTGRES_PASSWORD=local-vt033-only -e POSTGRES_DB=vt033 -p 127.0.0.1:15433:5432 postgres:16-alpine
docker exec vt033-pg pg_isready -U vt033 -d vt033
```

Nếu container đã tồn tại, kiểm tra trước khi chọn `docker start vt033-pg`; không tự xóa/replace container hoặc volume. Dùng DSN riêng trong CMD **ở phiên terminal đang chạy test**:

```bat
set "TEST_DATABASE_URL=postgresql+psycopg://vt033:local-vt033-only@127.0.0.1:15433/vt033"
set "DATABASE_URL=%TEST_DATABASE_URL%"
```

PowerShell tương đương:

```powershell
$env:TEST_DATABASE_URL = 'postgresql+psycopg://vt033:local-vt033-only@127.0.0.1:15433/vt033'
$env:DATABASE_URL = $env:TEST_DATABASE_URL
```

Nếu password khác thì DSN phải khớp. Không ghi DSN chứa mật khẩu vào log được commit. Test fixture `tests/notification/test_postgres.py` tạo/xóa sibling database riêng và đòi quyền CREATEDB; không được trỏ vào một database có dữ liệu không được phép xóa. Kiểm tra migration trên DB test mới bằng `alembic upgrade head` trước test full-suite nếu repo yêu cầu. Không chạy `docker compose down -v`.

### 2.3. Local baseline evidence

Trước mọi chỉnh sửa production, chạy test gốc và lưu log/exit code/test counts, môi trường, timestamp, baseline SHA. Ưu tiên các lệnh trong `services/core/tests/README.md`:

```bat
.venv\Scripts\python.exe -m ruff check app tests migrations
.venv\Scripts\python.exe -m ruff format --check app tests migrations
.venv\Scripts\python.exe -m pytest tests/notification/test_contract.py -q -W error -p no:cacheprovider
.venv\Scripts\python.exe -m pytest tests/notification/test_postgres.py -q -W error -p no:cacheprovider
```

Nếu đủ điều kiện, chạy full baseline với `pytest -q -W error -p no:cacheprovider --junitxml=...` và coverage; kiểm tra số test skipped. Các test DB bị skip vì thiếu `TEST_DATABASE_URL` **không phải bằng chứng kiểm thử PostgreSQL**. Không lẫn baseline failures với test RED của thay đổi VT-033.

Lưu evidence tại đường dẫn hợp lý, ví dụ `docs/assignments/VT-033/evidence/` (log đã loại credential và dữ liệu riêng tư). File tạo ra do tool (`coverage.xml`, JUnit XML...) giữ đúng đường dẫn, không bịa đường dẫn. Chỉ commit log/anonymized summary cần thiết, không commit cả thư mục `.venv`, file `.env`, dữ liệu database.

## 3. REPOSITORY AUDIT + CÂU 1 — SPECIFICATION & PLAN (15 ĐIỂM)

Đọc source thực tế trước khi viết bất kỳ patch nào:
- `AGENTS.md`, `README.md`, `docs/architect/BUSINESS_RULES.md`;
- `services/core/README.md`, `services/core/tests/README.md`, `services/core/pyproject.toml`;
- `services/core/app/common/config.py`, `services/core/app/common/pagination.py`;
- `services/core/app/modules/notification/router.py`, `service.py`, `repository.py`;
- `services/core/tests/notification/test_contract.py`, `test_postgres.py`;
- `services/core/tests/performance/class_list_load.py`;
- các module khác gọi `get_pagination` và tài liệu API liên quan.

### Chức năng đề xuất: Notification default page size configurable

Ở baseline đã biết `get_pagination(... Query(ge=1, le=100))` dùng giá trị mặc định `20` tại `common/pagination.py`; Notification `GET /api/v1/notifications` đang dùng dependency chung này. Đề xuất cấu hình **default notification page size** tập trung, ví dụ `NOTIFICATION_PAGE_SIZE_DEFAULT`, mặc định 20 và phạm vi hợp lệ 1–100. Cấu hình áp dụng khi process nạp settings/restart, **không hứa hẹn thay đổi động runtime** nếu kiến trúc không hỗ trợ.

Phải giữ nguyên khi không có cấu hình mới: mặc định 20, tham số query `limit` hợp lệ 1–100, response `{items, unread_count, next_cursor}`, cơ chế cursor, `Cache-Control: no-store`, identity/authorization, không đổi pagination của endpoint khác. Ưu tiên dùng `Settings`/`pydantic-settings` sẵn có. Tránh sửa global pagination nếu sẽ ảnh hưởng module khác. Không tự biến đề xuất này thành business rule nếu tài liệu có mâu thuẫn; nếu phát hiện mâu thuẫn, điều chỉnh vertical slice nhưng vẫn phải đáp ứng change request VT-033 và nêu evidence.

**Câu 1 cần viết đầy đủ:**
1. Một problem statement rõ ràng, phạm vi và lý do hardcoding khó bảo trì.
2. **3–5 acceptance criteria** kiểm chứng được; ưu tiên cấu hình mặc định, explicit limit, invalid config/input, quyền thông báo, regression.
3. Ít nhất **2 non-functional constraints**, bao gồm patch tối thiểu/dependency và 120 concurrency/p95 <=3.5s.
4. Invariant: *User A không bao giờ đọc hoặc đánh dấu đọc notification thuộc User B, bất kể cấu hình pagination.* Nêu pre/postconditions.
5. **AI-assisted implementation plan TRƯỚC khi code**, lưu nguyên prompt chính, assumptions, files dự kiến sửa, trình tự RED → GREEN, risk, rollback.
6. **Review kế hoạch bằng repository thật**, nêu **>=2 đề xuất AI thực sự đã sửa/bác bỏ** kèm trích dẫn file/line/commit và giải thích (ví dụ: không thêm library vì `pydantic-settings` đã có; không sửa global `get_pagination` vì dùng chung). Không bịa việc AI đã đề xuất nếu không có output thật.

Đừng bắt đầu production patch khi chưa có bản kế hoạch lưu dưới `docs/assignments/VT-033/` và review độc lập. Để sinh viên duyệt những điểm nhạy cảm, đánh dấu mục cần human review; không gán nhãn “human-approved” khi chưa được duyệt.

## 4. CÂU 2 — RISK-BASED TEST STRATEGY (20 ĐIỂM)

Lập kế hoạch unit, integration/API, E2E (giải thích trường hợp nào không cần E2E), mapping test theo risk. Tạo bảng **>=10 test cases** có cột: `ID | Risk/AC | Level | Preconditions/Input | Expected business outcome | Priority | Test file`.

**Boundary Value Analysis:** cho input và cấu hình phạm vi 1–100: `0, 1, 2, 99, 100, 101`, đồng thời test mặc định 20, custom 1/2/100 và explicit `limit`. Xác minh startup/validation đối với invalid env setting nếu đúng thực tế, không thay silent fallback thành chính sách không được duyệt.

Bắt buộc >=2 negative tests và >=1 failure-path. Test bắt buộc kiểm tra **business outcome**: `items` thuộc đúng user, thứ tự/ID, số lượng đúng, next_cursor đúng, unread_count đúng, `read_at` của user khác không đổi; status code chỉ là một phần expected result. Có regression đối với endpoint khác dùng pagination.

Không làm giả coverage hoặc E2E; giải thích test nào có giá trị thấp/không cần thiết và giới hạn bởi service đang triển khai.

## 5. CÂU 3 — TEST-FIRST AI-ASSISTED IMPLEMENTATION (25 ĐIỂM)

### 5.1 RED evidence (local trước khi sửa implementation)
- Viết test nhỏ nhất cho cấu hình notification mới; lựa chọn level phù hợp, không overmock làm mất behavior.
- Chạy đúng test trên **code baseline chưa patch** và xác nhận **FAIL do thiếu hành vi**, không phải import/error/DB unavailable.
- Lưu command, exit code, test name, traceback trọng yếu, timestamp, git SHA, trạng thái env và log (redact secrets).
- Commit test RED trước nếu phù hợp: `test(vt033): specify configurable notification pagination`.
- Không thay đổi code production trước khi thu được RED evidence thật.

### 5.2 GREEN patch và kiểm thử lại
- Patch tối thiểu ở Notification và `Settings` nếu cần; tránh thay đổi `get_pagination` chung và public API ngoài phạm vi.
- Review `git diff --check`, `git diff --stat`, `git diff`, kiểm tra business rules, authorization, shared calls, backward compatibility, unsupported edge cases; không tự thêm dependency/migration nếu không có lý do.
- Chạy RED tests lại (phải PASS), test Notification regression, integration PostgreSQL thật, lint và full core suite nếu khả thi. Ghi PASS/FAIL/SKIP riêng; không đổi nhãn fail thành pass.
- Commit production patch riêng: `fix(vt033): configure default notification page size`.
- Giữ test và implementation ở commit khác nhau nếu khả thi để chứng minh test-first chronology.
- Nếu repo không chạy được integration, làm executable characterization/harness cho module gần nhất, ghi giới hạn chính xác; không được coi mock PASS là DB verification.

## 6. CÂU 4 — WHO TESTS THE TESTS? (MUTATION, COVERAGE, FLAKY, LOAD)

### 6.1 Mutation authorization — chỉ LOCAL, không push lỗi

Tại baseline, `NotificationRepository.mark_read(notification_id, user_id)` lọc theo notification ID **và** `recipient_id`. Tạo deliberate mutation có phạm vi **một đường đi**: tạm bỏ điều kiện `recipient_id` trên đường đánh dấu đã đọc. Thực hiện **sau khi đã commit patch đúng**, trên working tree cô lập hoặc branch tạm **KHÔNG PUSH**, với test database dành riêng. Bắt buộc:
1. Test bảo mật trên code đúng PASS; chứng minh User A không mark-read notification của User B và `read_at` của B không đổi.
2. Lưu diff mutation chỉ gồm việc bỏ authorization guard.
3. Chạy lại cùng test, xác nhận mutation bị **KILLED** vì test thất bại với sai lệch business outcome.
4. Nếu mutation **SURVIVED**, viết/bổ sung test bảo mật, xác minh lần hai.
5. **Hoàn nguyên mutation tuyệt đối**, chạy test bảo mật và regression trở lại PASS.
6. Trước commit/push kiểm tra `git diff` và source: điều kiện authorization đã trở lại, branch nộp **không chứa mutation**.

Không dùng `git restore` bừa bãi nếu file có thay đổi hợp lệ chưa commit. Không ghi mutation vào commit nộp hoặc PR. Evidence mutation lưu log/diff đã khử thông tin nhạy cảm.

### 6.2 Coverage và flaky risks

Sử dụng `pytest-cov` có sẵn: line + branch coverage và risk coverage theo AC, nói rõ missing branches; **không chỉ dựa vào % coverage** để kết luận chất lượng. Kiểm tra >=2 nguy cơ flaky bằng chạy lặp/reorder hoặc kiểm soát fixture: (a) order/shared DB state, (b) time/concurrency/network/randomness. Ghi lệnh chạy, kết quả, limit và cách giảm flaky.

### 6.3 Performance — BẮT BUỘC 120 concurrent tasks

`tests/performance/class_list_load.py` hiện đo class-list và giới hạn **100** user; nó **không chứng minh VT-033**. Tạo harness mới cho Notification, ưu tiên `tests/performance/vt033_notification_load.py`, tái sử dụng thiết kế tốt nếu phù hợp, không phá harness chung.

Yêu cầu:
- Thực sự chạy với 120 actors/tasks song song trên local nếu máy và DB đáp ứng. Phân biệt **120 tác vụ đang hoạt động đồng thời** với chỉ tổng 120 request gửi lần lượt; ghi rõ closed-loop/arrival rate, warmup, duration.
- HTTP tới app thật (local loopback) và PostgreSQL test độc lập; các actor có dữ liệu tổng hợp riêng, token test không ghi log; không cần gọi service AI bên ngoài.
- Kiểm tra response **nội dung và user ownership**, không chỉ status.
- Dùng `time.perf_counter`, đo p50/p95/p99/max, số lượng request, error rate, status distribution, timeout, CPU/RAM/OS/Python/PostgreSQL, pool size, run ID, baseline/patch SHA. Báo cả client và server latency nếu có.
- So sánh **p95 client-observed** với 3500 ms; p95 thực tế không đạt thì báo FAIL và phân tích, không đổi mục tiêu.
- Smoke ngắn chỉ chứng minh harness chạy; một lần tải nghiêm túc cần thời lượng, warmup và cỡ mẫu đủ hợp lý, ghi rõ giới hạn máy local.
- Nếu không thể tải thật: vẫn tạo harness chạy được, thử ở mức thực tế, trình bày cấu hình/dữ liệu giả lập và **không tuyên bố 120 PASS**.
- Không tận dụng DB/service đang chạy production và không đo bằng mock rồi gọi là HTTP/database performance.

## 7. CÂU 5 — TRACEABILITY, AI USAGE LOG, REFLECTION

Tạo traceability `AC/Risk → Test ID → Test file/function → Commit SHA/PR → Observed result/evidence` cho tất cả AC. AI Usage Log ghi tên công cụ/model nếu biết, prompt chính thật, đề xuất, diff đã dùng/sửa/bác bỏ, verification evidence; không có nội dung giả. Chỉ ra >=2 điểm AI-generated code/test hợp lý bề ngoài nhưng không đáng tin, như assert status-only hoặc mock bỏ sót authorization. Viết reflection **250–350 từ tiếng Việt**, dựa trên kết quả thật: confidence tăng bởi gì, chưa chứng minh điều gì, residual risk, test tiếp theo giá trị cao nhất. Người học phải đọc/review và chịu trách nhiệm về nội dung; không giả mạo hành động duyệt của người học.

## 8. EVIDENCE & REPRODUCIBILITY — LÀM TRÊN LOCAL

- Tổ chức các file `docs/assignments/VT-033/` hoặc thư mục hợp lý với: spec, AI plan, plan review, test cases, traceability, AI Usage Log, README riêng và evidence đã lọc.
- Đặt tên dễ truy vết `00-baseline`, `01-red`, `02-green`, `03-mutation`, `04-restored`, `05-coverage`, `06-flaky`, `07-load`, kèm metadata timestamp/SHA/command/exit status.
- Log FAIL phải là FAIL do assertion của thay đổi; mutation fail phải do bảo mật, không do môi trường.
- Chạy lệnh tái lập bằng đường dẫn `.venv\Scripts\python.exe` trên Windows; hướng dẫn riêng CMD vs PowerShell cho environment variables.
- Bảo đảm `git status --short`, `git diff --check`, số lượng tests và file log khớp với báo cáo.
- Các test DB bị skipped không được tính thành PASS DB. Nếu không thể chạy một nhóm test, nêu nguyên nhân và risk chưa được verify.
- Không commit `.env`, venv, tokens, passwords, DSN secrets, personal data. Không xóa container/volume hiện có để xử lý failure.

## 9. LOCAL → GITHUB DELIVERY (BẮT BUỘC, SAU KHI TEST)

Sau khi local verification và kiểm tra mutation đã hoàn nguyên:

1. `git status` + `git diff --check`; kiểm tra chỉ file liên quan, không có secret/mutation.
2. Commit có ý nghĩa: RED tests, implementation, bổ sung tests/harness, docs/evidence.
3. Push **branch riêng**, ví dụ (từ root repo):

```bat
git push -u origin assignment/23001878-vt033-notification-config
```

4. Tạo **Draft Pull Request** từ branch cá nhân vào `main` bằng GitHub CLI (`gh pr create --draft --base main --head ...`) nếu `gh` đã cài và đăng nhập, hoặc dùng GitHub web/connector. Không coi `gh` là dependency ứng dụng. PR title: `[VT-033][23001878] Configurable notification pagination with risk-based tests`.
5. PR body: baseline SHA, AC, scope, file changed, RED/GREEN logs và commands, mutation killed/survived, coverage, flaky review, 120 concurrency/p95 (hoặc honest limitations), AI usage disclosure, `DO NOT MERGE — pending team review`.
6. **GitHub Actions:** Workflow Core CI tự chạy trên `pull_request` (dù push trực tiếp lên `assignment/**` không kích hoạt theo filter hiện tại). Đọc CI run thật, xác nhận pytest/PostgreSQL/JUnit/coverage; nếu CI fail, điều tra và sửa cẩn trọng, chạy lại local trước khi push. GitHub CI là kiểm tra độc lập, không thay thế bằng chứng test-first local.
7. Xác minh branch URL/PR URL thật, head SHA, PR ở trạng thái Draft/OPEN, `base=main`, changed files chứa test + patch, không có mutation; không merge.

Nếu chưa có GitHub CLI/quyền tạo PR, **không trì hoãn local work**: hoàn thành local, thử push nếu được phép và hướng dẫn tạo Draft PR qua GitHub web; ghi blocker chính xác, không bịa URL. Nếu push bị từ chối, giữ commit local và báo cách cấp quyền; không push qua branch của thành viên khác.

## 10. BÁO CÁO PDF — TẠO TỪ EVIDENCE THẬT

Tạo một PDF duy nhất `BT3_23001878_VT-033.pdf` **trên máy local**, tối đa 8 trang nội dung chính (phụ lục AI Usage Log/ảnh/log thực thi không tính). Không cần cài thư viện mới vào project để xuất PDF: ưu tiên công cụ tài liệu sẵn có trên máy hoặc tạo nguồn Markdown/HTML và lệnh xuất rõ ràng; tách dependency báo cáo khỏi runtime Core.

Trang đầu bắt buộc: Mai Huy Hoàng, 23001878, VT-033, SE2026-T09, AI-01, repository, baseline SHA, link GitHub branch và Draft PR thực tế. Cam kết nguyên văn:

"Tôi chịu trách nhiệm về toàn bộ code, test và nội dung bài làm; tôi đã khai báo việc sử dụng AI."

Nội dung chính: Specification/AC/invariant; AI plan + >=2 review decisions; strategy + >=10 cases + BVA; RED→GREEN; mutation; coverage/flaky/load; traceability; reflection 250–350 từ; limitations. Đính kèm phụ lục AI Usage Log và evidence đã làm sạch. Kiểm tra font tiếng Việt, số trang, PDF mở được, link clickable và không bịa số liệu.

**Quan trọng:** Bài nộp trên Classroom gồm PDF và link branch/PR; PDF chỉ thực sự hoàn chỉnh khi có URL thật. Nếu GitHub chưa sẵn, ghi bản báo cáo DRAFT local và cập nhật link sau khi push.

## 11. TRÌNH TỰ THỰC THI KHÔNG ĐẢO LỘN

1. Kiểm tra đường dẫn local, `git status`, baseline, branch, Python/Docker/PostgreSQL; lưu metadata.
2. Audit source, requirements, lập AI plan trước code; review >=2 đề xuất bằng evidence.
3. Thiết kế risk-based tests + BVA + traceability dự kiến.
4. Chạy baseline; viết test mới, chạy RED đúng lý do; lưu log và commit test nếu phù hợp.
5. Tạo patch nhỏ nhất; diff review; chạy GREEN/integration/full regression trên local.
6. Mutation authorization trong working tree/branch tạm; ghi killed/survived, restore hoàn toàn; rerun tests.
7. Coverage, flaky review; chạy 120-concurrency harness trên local hoặc ghi rõ giới hạn nếu không thể.
8. README, evidence, AI Usage Log, reflection, traceability.
9. Commit/push branch cá nhân, tạo Draft PR, xác minh GitHub Actions và link thật; không merge.
10. Xuất PDF chính thức đủ thông tin và tự kiểm tra trước khi nộp.

Làm liên tục trong phạm vi quyền được cấp. Chỉ hỏi người dùng khi có rủi ro thao tác phá dữ liệu, thiếu credential/quyền gây blocker, hoặc quyết định đổi business rule. Không tạo prompt vô hạn vòng lặp, không đòi local test phải do chính người dùng gõ nếu agent có terminal thực thi. Nếu không thể thực thi, nói rõ lý do và cung cấp lệnh copy/paste đúng Windows shell.

## 12. FINAL QUALITY GATE & BÀN GIAO

Trước khi báo hoàn thành, tự đối chiếu mọi điểm rubric: specification (1 statement, 3–5 AC, >=2 NFR, invariant, plan-before-code, >=2 plan corrections); >=10 test cases, BVA, >=2 negative, 1 failure path; test-first RED→GREEN có SHA/log; mutation authorization bị test bắt và hoàn nguyên; coverage/risk coverage, >=2 flaky risks; executable 120 concurrency và p95 vs 3.5s hoặc giới hạn; traceability, AI Usage Log, 2 AI trust issues, reflection 250–350 từ; README; GitHub branch/PR thực; PDF <=8 trang nội dung chính.

**Cuối cùng trả về theo mẫu (chỉ điền thông tin đã kiểm chứng):**

### Local
- Local repo: `D:\app\cnpm\W3\SE2026_T09_RAG_course_assistant`
- Baseline SHA / branch / head SHA:
- Python/Docker/PostgreSQL version:
- Test baseline: passed/failed/skipped, command/log:
- RED: command / failed assertion / exit code / log:
- GREEN: command / passed/failed/skipped / log:
- Mutation: diff / killed-or-survived / restored proof:
- Coverage line/branch/risk:
- Flaky experiments:
- 120 concurrent: actual workers/tasks, requests, p95, status/error count, machine info, limitations:
- Files changed and human review items:

### GitHub
- Branch URL (real):
- Draft PR URL (real):
- Head commit SHA:
- GitHub CI run URL and result:
- PR Draft/OPEN? Mutation absent? Unmerged?:

### Submission
- PDF path: `BT3_23001878_VT-033.pdf`
- Main page count and appendix:
- README/test commands:
- Remaining blockers and unverified claims:

**Không tuyên bố hoàn thành nếu chưa xác minh bằng evidence thật. Tuyệt đối không merge PR. BẮT ĐẦU NGAY TẠI THƯ MỤC LOCAL ĐÃ CÓ, KHÔNG CLONE LẠI REPOSITORY.**
