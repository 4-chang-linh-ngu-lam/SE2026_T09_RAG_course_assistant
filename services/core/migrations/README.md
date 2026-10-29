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

Head hiện tại là `0013`. `app/model_registry.py` là composition root đăng ký
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

School đã có ở `0008`; `users.school_id` vẫn nullable và **chưa có FK**. Tài khoản
cũ có thể thiếu scope, hoặc scope chưa có School row. Workflow Classroom hiện có
tạo School từ scope đã được gán cho Admin; việc đó không xác định mapping legacy.
Chưa có manifest dữ liệu thực được owner TV1/TV2 duyệt trong task này, nên không
backfill hoặc thêm FK tự động. Audit legacy thiếu school-at-event-time giữ null;
không backfill audit bằng school hiện tại của user.

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
commit/rollback toàn bộ unit of work.

Sau mapping, Admin dùng workflow Identity/Administration hiện có để chuyển
username/cấp mã theo đúng trạng thái. Chỉ đề xuất revision FK sau khi report sạch,
mapping được duyệt và contract tạo School trước Identity được owner thống nhất;
không coi School entity tồn tại là đủ điều kiện bật constraint.

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
Trước khi chạy, operator xác minh URL, hostname Neon staging, database đích và SMTP Gmail
đã cấu hình. Trên job, cung cấp `STAGING_BOOTSTRAP_ADMIN_EMAIL`,
`STAGING_BOOTSTRAP_SCHOOL_NAME` (synthetic `Lumi Staging`) cùng `SMTP_*`; `SMTP_PASSWORD`
chỉ tham chiếu Secret Manager, không phải plaintext env/argument. Notification worker Job
cũng phải dùng cùng `DATABASE_URL`, `SECRET_KEY` và SMTP secrets để gửi invitation đã queue.

Lệnh kiểm tra migration head, environment/confirmation, đúng database name + host và
khóa Core tables. Nó từ chối database có dữ liệu ứng dụng hoặc marker không khớp. Lần đầu
tạo một School và một Admin `PENDING_VERIFICATION` cùng audit/credential-delivery record
trong một transaction; Core chỉ lưu token hash/durable retry state. Lần chạy lại cùng
profile chỉ trả IDs/status, không tạo token mới. Output không chứa email, password hay
token; invitation token được worker gửi qua email để người nhận tự đặt mật khẩu. Không
chạy lệnh này cho Production; PR không tạo hoặc thực thi Cloud Run Job trên Neon.

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
