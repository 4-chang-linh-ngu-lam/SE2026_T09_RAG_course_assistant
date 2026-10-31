# Core migrations và dữ liệu dev/test — TASK-014

Chạy các lệnh từ `services/core`, trong môi trường đã cài `.[dev]`; đặt
`DATABASE_URL` qua môi trường của tiến trình. PostgreSQL 16 là đích kiểm thử.
Không dùng database đang phục vụ người dùng để thử seed hoặc downgrade.

## Nâng cấp và kiểm tra schema

```sh
python -m alembic upgrade head
python -m alembic check
python -m alembic heads --verbose
python -m app.maintenance report
```

Head hiện tại là `0014`. `app/model_registry.py` là composition root đăng ký
model của các module đã triển khai; không thêm entity rỗng để đủ số bảng.
Alembic chỉ so sánh schema `core`, version table là `core.alembic_version`.
Không có FK đến service khác. FK membership/assignment giữ lịch sử khi kết
thúc membership hoặc khóa user; quyền cross-school còn được kiểm tra tại workflow.

Migration online lấy advisory transaction lock; schema setup, kiểm tra downgrade
và DDL nằm trong cùng transaction. Không sửa revision đã áp dụng. Khi thêm
feature, tạo revision từ head thực tế, thêm model vào registry nếu cần và kiểm tra
`alembic check`. Thêm bảng mới phải bổ sung vào
`app/maintenance/migration_safety.py:TABLES_INTRODUCED`; thay đổi cột cần quy tắc
giữ dữ liệu riêng trong guard và test tương ứng. Test kiểm tra mọi bảng model đều
được khai báo trong danh sách bảo vệ. Không tạo revision mới nếu không đổi schema.

## Mapping School cho dữ liệu cũ

School đã có ở `0008`; migration `0014` thêm FK nullable từ `users.school_id` đến
`schools.id`, không backfill tài khoản hoặc bắt buộc mọi user có scope. FK được
thêm `NOT VALID` để orphan cũ không chặn deployment; migration tự validate ngay
nếu không còn orphan. FK `NOT VALID` vẫn chặn giá trị orphan mới. Nếu còn orphan,
chạy plan/apply mapping đã xác minh; apply chỉ validate constraint sau khi mọi
`school_id` khác null trỏ tới School. User chưa có mapping tiếp tục giữ
`school_id=NULL` và bị workflow yêu cầu school scope từ chối. Audit legacy thiếu
school-at-event-time giữ null; không backfill bằng school hiện tại của user.

Test có thể dùng School/User UUID tổng hợp để kiểm tra migration trong database
`test_`/`dev_` riêng. Không dùng UUID tổng hợp để gán tài khoản staging/production.
Mapping thật vẫn cần nguồn có thẩm quyền được owner TV1/TV2 xác minh trước khi
áp dụng vào database thật.

`report` chỉ đọc, trả UUID, trạng thái/role, version, các School và issue codes:
`MISSING_SCHOOL_SCOPE`, `SCHOOL_ENTITY_MISSING`, `INVALID_USERNAME`,
`DUPLICATE_USERNAME`, `STUDENT_USERNAME_NOT_MIGRATED`,
`STUDENT_ACTIVATION_PENDING`, `CROSS_SCHOOL_HISTORY`. Không xuất email,
username gốc, hash, token, mã hoặc nội dung yêu cầu dữ liệu. Roster/membership/
assignment gồm cả lịch sử được báo bằng School UUID, không suy ra mapping từ đó.

Owner chuẩn bị file JSON theo dữ liệu đã xác minh, ví dụ cấu trúc:

```json
{
  "schools": {"<School UUID đã duyệt>": "<Tên trường đã duyệt>"},
  "assignments": {"<User UUID>": "<School UUID đã duyệt>"}
}
```

Không dùng các chuỗi minh họa làm dữ liệu thật. Có thể khai báo School theo UUID
scope đang được dùng, hoặc tham chiếu School đã tồn tại mà không cần khai báo lại.
School có tên khác manifest bị chặn; tên null chỉ được điền theo manifest rõ ràng.

```sh
python -m app.maintenance plan-school-mapping --manifest mapping.json
# Review toàn bộ output và manifest; lấy plan_sha256 từ kết quả.
python -m app.maintenance apply-school-mapping --manifest mapping.json --approved-sha256 <plan_sha256>
python -m app.maintenance report
```

Apply là thao tác offline: dừng Core/worker và các writer trước khi chạy; backup
database theo quy trình của môi trường. CLI khóa các bảng Core theo thứ tự trong
một transaction, rồi tính lại mã kiểm tra từ manifest/database/revision/trạng thái
hiện hành. Sai mã hoặc dữ liệu thay đổi thì rollback. Không được dùng kết quả hash
thay cho review owner. Chỉ gán scope còn thiếu hoặc giữ nguyên scope khớp; không
đổi trường đã gán, không tạo mapping trái với lịch sử Classroom. UUID/hash/status,
data requests và token history được giữ. Khi scope thay đổi, tăng session_version,
revoke refresh sessions và ghi audit `LEGACY_ASSIGN_SCHOOL`; không tự mở LOCKED,
verify email, gán username hoặc activate Student. School khai báo được audit
`LEGACY_REVIEW_SCHOOL`. Caller dùng public helpers với explicit session phải tự
commit/rollback toàn bộ unit of work. Apply từ chối nếu còn giá trị `school_id`
orphan và chạy `VALIDATE CONSTRAINT` trong cùng transaction; khi đó mọi thay đổi
rollback. `school_id=NULL` được giữ nguyên và không cản FK validation.

Migration `0014` giữ FK nullable và để NOT VALID khi DB còn orphan School references.
Sau mapping, Admin dùng workflow Identity/Administration hiện có để chuyển
username/cấp mã theo đúng trạng thái; apply mapping validate FK khi không còn orphan.
Không coi School entity tồn tại là đủ để suy ra mapping cho user.

## Seed chính thức cho dev/test

Tạo một database **riêng, sạch**, tên bắt đầu `dev_` hoặc `test_`; account dùng cho
seed cần quyền migration và ghi schema đó. Chỉ định chính xác database qua
`DATABASE_URL` và `--expected-database`. Mật khẩu Admin riêng do người chạy cung
cấp trong `CORE_SEED_ADMIN_PASSWORD` (12–128 ký tự), không đưa vào command line,
file commit hoặc log. Không có mật khẩu mặc định. Sau khi cấu hình môi trường:

```sh
python -m alembic upgrade head
python -m app.maintenance seed-dev --environment development --expected-database dev_lumi --school-id <UUID-rieng-cho-fixture> --school-name "Lumi Synthetic School"
python -m app.maintenance seed-dev --environment development --expected-database dev_lumi --school-id <cung-UUID> --school-name "Lumi Synthetic School"
```

Kết quả đầu `created:true`, lần sau `created:false`; chỉ trả School UUID và kết quả.
Đổi profile trên database đã seed bị từ chối; không reset credential hoặc ghi đè
dữ liệu đã chỉnh sau seed. Database có dữ liệu Core nhưng chưa có marker seed bị
từ chối. Migration và seed không tự chạy seed trong Compose/startup.

Seed tạo School rồi Admin `admin@seed.example.com` trong fixture Identity sở hữu;
đây là bootstrap offline cho database rỗng, không đăng ký route HTTP. Hai Lecturer
`primary@seed.example.com`, `assisting@seed.example.com` dùng invitation/reset
workflow thật. Student `seed.student.1`, `.2` dùng create/activation workflow thật;
`.3` còn PENDING để thử cấp lại mã. Mỗi tài khoản ngoài Admin có mật khẩu ngẫu nhiên
riêng bị bỏ sau thao tác; không gửi email, trả/lưu raw token/code hoặc dùng chung
mật khẩu. Đăng nhập Admin bằng mật khẩu người chạy cung cấp; dùng workflow hiện có
khi cần cấp lại mã Student. Token hash/history vẫn lưu đúng mô hình Identity.

Classroom tạo course, 7 homeroom khối 6–12, 14 lớp môn học AUTO/MANUAL, PRIMARY/
ASSISTING qua service nghiệp vụ thuộc module, transaction do coordinator sở hữu.
Hai Student được ghi roster khối 9, AUTO sync; một Student vào lớp MANUAL khối 9.
Các lớp khối khác để trống. Audit/outbox từ các workflow commit cùng dữ liệu seed.
Marker `DEV_SEED_COMPLETED` chỉ ghi khi toàn bộ thành công. Chạy đồng thời được
serialize; lỗi giữa chừng rollback tất cả. Không dùng bootstrap demo-ui.

### Bộ mock thủ công cho issue #18

Khi chưa có trường đối tác, dùng bộ synthetic này trong database `test_`/`dev_`
riêng để diễn tập onboarding; không gọi đây là dữ liệu Production:

| Thành phần | Giá trị mock |
|---|---|
| Trường | `Lumi Mock School`; School UUID tự tạo riêng cho fixture và giữ nguyên khi chạy lại seed |
| Admin vào hệ thống | `admin@seed.example.com`; mật khẩu do người chạy đặt qua `CORE_SEED_ADMIN_PASSWORD` |
| Giáo viên | `primary@seed.example.com`, `assisting@seed.example.com` |
| Học sinh | `seed.student.1`, `seed.student.2` (đã kích hoạt); `seed.student.3` (đang chờ mã) |
| Lớp/roster | Khối 6–12, AUTO/MANUAL, PRIMARY/ASSISTING; hai học sinh ở roster khối 9 |

Seed không gửi thư và không trả mật khẩu/mã đã sinh cho các tài khoản ngoài Admin.
Muốn mock đăng nhập giáo viên/học sinh, dùng sender giả trong test hoặc cấp invitation/
activation qua workflow hiện có; không gửi thư đến địa chỉ giả qua SMTP thật. UUID user
để thử mapping phải lấy từ fixture/report của database test, không tự đoán.

## One-time Admin bootstrap cho staging Preview

Lệnh CLI:

```sh
python -m app.maintenance bootstrap-staging-admin --environment staging --expected-database neondb --expected-host <Neon-host> --confirm-staging-bootstrap
```

Lệnh chỉ dành cho một Cloud Run Job operator-triggered dùng Secret Manager
`lumi-neon-staging-database-url` làm `STAGING_DATABASE_URL` (PostgreSQL URI; CLI dùng
driver `psycopg` nếu scheme chưa khai báo driver); `STAGING_DATABASE_HOST`
phải là hostname Neon staging đã duyệt và lệnh `--expected-host` phải khớp. Job cũng
có thể cần `DATABASE_URL` để khởi tạo cấu hình Core, nhưng bootstrap chỉ kết nối qua
`STAGING_DATABASE_URL`. URI không được có tham số query `host`, `hostaddr`, `service`
hoặc `servicefile`, vì chúng có thể chuyển hướng kết nối khỏi hostname staging. Đây
không phải HTTP route, seed tự động, hay production onboarding.
Trước khi chạy, operator xác minh URL, hostname Neon staging, database đích, SMTP Gmail và
`PUBLIC_WEB_URL` trỏ đúng Vercel Preview đã cấu hình. Trên job, cung cấp
`STAGING_BOOTSTRAP_ADMIN_EMAIL`, `STAGING_BOOTSTRAP_SCHOOL_NAME` (synthetic `Lumi Staging`)
cùng `SMTP_*`; `SMTP_PASSWORD`
chỉ tham chiếu Secret Manager, không phải plaintext env/argument. Notification worker Job
cũng phải dùng cùng `DATABASE_URL`, `SECRET_KEY`, `PUBLIC_WEB_URL` và SMTP secrets để gửi lời mời đã xếp hàng.

Lệnh kiểm tra migration head, environment/confirmation, đúng database name + host và
khóa Core tables. Nó từ chối database có dữ liệu ứng dụng hoặc marker không khớp. Lần đầu
tạo một School và một Admin `PENDING_VERIFICATION` cùng audit/credential-delivery record
trong một transaction; Core chỉ lưu token hash/durable retry state. Lần chạy lại cùng
profile chỉ trả IDs/status, không tạo token mới. Output không chứa email, password hay
token; invitation email của nhân sự có link đến `PUBLIC_WEB_URL/staff/invitation`, còn
Student activation/recovery vẫn là mã Admin bàn giao trực tiếp. Không chạy lệnh này cho
Production; PR không tạo hoặc thực thi Cloud Run Job trên Neon.

Nếu operator nhập sai email nhưng invitation chưa được gửi, có thể sửa người nhận bằng
lệnh staging-only:

```sh
python -m app.maintenance correct-staging-admin-email --environment staging --expected-database neondb --expected-host <Neon-host> --confirm-staging-admin-email-correction
```

Job cung cấp `STAGING_BOOTSTRAP_EXPECTED_ADMIN_EMAIL` (email hiện tại),
`STAGING_BOOTSTRAP_ADMIN_EMAIL` (email mới) và `STAGING_BOOTSTRAP_SCHOOL_NAME`.
Lệnh chỉ đổi email của đúng Admin pending trong đúng School; đòi hỏi đúng marker, một
invitation còn hạn, delivery `PENDING` và `attempts=0`. Nó vô hiệu token cũ, tạo
invitation token mới cho địa chỉ sửa và ghi audit; không in email/token. Token mới cần
được phát qua worker như thường lệ. Nếu đã có lần gửi/thử gửi, lệnh từ chối; operator
phải điều tra trạng thái delivery trước khi chọn luồng xử lý tiếp theo.

## Production mock deployment and one-time bootstrap

Theo quyết định của chủ dự án (2026-10-30), Production hiện là môi trường đồ án
dùng dữ liệu tổng hợp `Lumi Mock School`, không phải trường đối tác. Neon Production
được tạo tách khỏi staging ở Singapore, PostgreSQL 16, project
`lumi-production-mock`, database `neondb`. Không nhập dữ liệu người học thật.

Cloud Run Production API `lumi-core-api-production` đang chạy revision
`lumi-core-api-production-00001-qcm` tại
`https://lumi-core-api-production-ekiajqg6oa-as.a.run.app`. Service scale-to-zero,
chỉ một Uvicorn worker, giới hạn tối đa ba instance và public invoker; Core vẫn áp dụng
xác thực/ủy quyền trên các route nghiệp vụ. `CORS_ORIGINS` chỉ cho phép Production
domain của Web. `/health/live`, `/health/ready`, `/docs` và CORS preflight đã trả 200.

Migration chạy bằng job `lumi-production-core-migrate` với direct Neon URL;
`lumi-production-core-schema-check` chạy `alembic check`. Cả hai đã thành công trên
DB Production mới, bao gồm head 0014. Runtime API và notification worker dùng pooled
URL riêng. Job `lumi-production-notification-worker` chạy theo batch một lần; Cloud
Scheduler `lumi-production-notification-worker-15m` gọi job mỗi 15 phút theo giờ
`Asia/Ho_Chi_Minh`. Các secret chỉ được tham chiếu từ Secret Manager:
`lumi-neon-production-database-url` (pooled),
`lumi-neon-production-direct-database-url` (migration/bootstrap),
`lumi-core-production-secret-key`,
`lumi-internal-production-service-secret` và `lumi-smtp-password`.

Sau migration, job operator-triggered `lumi-production-admin-bootstrap` đã tạo
School `Lumi Mock School` cùng Admin `PENDING_VERIFICATION`, audit và durable
invitation trong một transaction. Một lần chạy notification worker hoàn tất thành
công; việc nhận thư trong hộp thư chưa được xác nhận. Bootstrap CLI:

```sh
python -m app.maintenance bootstrap-production-admin --environment production --expected-database neondb --expected-host <Production-Neon-direct-host> --confirm-production-bootstrap
```

Job dùng `PRODUCTION_DATABASE_URL` từ Secret Manager secret
`lumi-neon-production-direct-database-url`; host trong secret,
`PRODUCTION_DATABASE_HOST` và `--expected-host` phải khớp. Cloud Run API dùng riêng
pooled URL secret `lumi-neon-production-database-url`. URI không được có query
`host`, `hostaddr`, `service` hoặc `servicefile`. Environment cần
`PRODUCTION_BOOTSTRAP_ADMIN_EMAIL` và `PRODUCTION_BOOTSTRAP_SCHOOL_NAME=Lumi Mock School`;
helper chỉ chấp nhận đúng tên School mock, DB trống ở migration head và confirmation.
SMTP sender/password chỉ tham chiếu Secret Manager. Core API và worker cần
`PUBLIC_WEB_URL` đặt thành origin Vercel Production để liên kết mời/khôi phục mở đúng trang;
biến này không phải secret.

Lần đầu tạo School UUID và Admin `PENDING_VERIFICATION` cùng audit/durable invitation
trong một transaction. Lần chạy lại cùng profile là idempotent; profile/marker khác
hoặc DB đã có dữ liệu bị từ chối. Output chỉ có IDs/status, không có email/token/password.
Job `lumi-production-admin-bootstrap` là lệnh offline operator-triggered, không có
HTTP bootstrap route. Worker và scheduler Production phải dùng Production DB/secrets
riêng, không trỏ sang staging. Không chạy lại bootstrap để gửi lại lời mời.

Production image hiện được build với tag
`asia-southeast1-docker.pkg.dev/pelagic-cat-492008-i2/cloud-run-source-deploy/lumi-core:production-mock-20261030`
trước khi PR #38 được hợp nhất vào `main`. Source hiện đã ở `main`, nhưng Cloud Run
vẫn cần được build/deploy lại từ source đã hợp nhất để runtime và GitHub đồng bộ.
Đặt `PUBLIC_WEB_URL` trên Core API và notification worker thành origin Vercel Production
trước khi gửi invitation/reset link. Kiểm tra image digest và revision sau deploy.
Vercel Production `CORE_API_URL`/`WEB_ORIGIN` đã được trỏ tới Core Production và redeploy
hoàn tất. Trang Production trả 200; gọi `/api/v1/auth/refresh` không có session trả
`401 UNAUTHENTICATED` từ Core qua Next proxy, xác nhận upstream không còn 503. Luồng
đăng nhập/redeem Admin và browser acceptance đầy đủ vẫn cần kiểm tra riêng.

Mock list cho người dùng nhập thử trong seed dev/test là `admin@seed.example.com`,
`primary@seed.example.com`, `assisting@seed.example.com` và Student
`seed.student.1`–`.3`; các địa chỉ này không được đưa vào Production bootstrap. Production
chỉ nhận Admin email do chủ dự án chỉ định và School tổng hợp `Lumi Mock School`.

## Downgrade và bằng chứng kiểm thử

Online downgrade chặn trước DDL nếu revision sẽ bỏ bảng có dữ liệu, school scope
của audit, Student identifier/activation, hoặc outbox envelope/retry chưa biểu diễn
được ở bản cũ. Token purpose/CORRECTION/email-free còn được constraint lịch sử bảo
vệ. Không xóa bản ghi để ép downgrade. SQL downgrade offline bị từ chối vì không
thể kiểm tra dữ liệu; SQL upgrade range vẫn được sinh. Restore/review dữ liệu trước
khi chọn phiên bản đích, không tắt guard.

```sh
# TEST_DATABASE_URL: PostgreSQL 16 test riêng, account có CREATEDB.
python -m pytest tests/maintenance -q -W error -p no:cacheprovider
python -m pytest -q -W error -p no:cacheprovider
```

Mỗi test maintenance tạo/xóa database `test_maintenance_<UUID>`. Bộ test gồm
upgrade từ `0004`/head, giữ UUID/hash/status/request/session/token, empty roundtrip
về base và fixture legacy tương thích, từ chối downgrade không tương thích,
metadata drift và schema khác service, seed lặp/rollback/concurrency/CLI thật,
mapping review/drift/cross-school, membership/assignment cạnh tranh, unique/FK và
Calendar time constraint, audit/outbox sau commit. Thiếu TEST_DATABASE_URL thì test
PostgreSQL skip, không được dùng kết quả đó làm bằng chứng nghiệm thu DB.

Core CI chạy migration/check/heads/report trước suite PostgreSQL 16, lưu report và
JUnit/coverage artifacts. Compose của TASK-016 đã yêu cầu migrate thành công trước
Core/notification-worker; không đổi thứ tự này. Kết quả local ghi tại TASK-014;
chưa thay thế kết quả CI remote hoặc review owner của mapping dữ liệu thực.
