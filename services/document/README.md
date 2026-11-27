# Document Service Foundation

Document là service độc lập, sở hữu database/schema và volume file riêng. Foundation này chỉ có health checks, model/migration ban đầu và storage adapter; chưa có public Document API, upload/CRUD, grants, Service JWT consumer, AI client/worker hay version activation.

## Ranh giới dữ liệu

- PostgreSQL instance có thể dùng chung, nhưng Document dùng database `lumi_document`, login role và `DOCUMENT_DATABASE_URL` riêng. Schema migration là `document`; không đọc Core DB và không có FK tới Core user/classroom IDs.
- Compose profile `document` khởi tạo database và role local trên PostgreSQL hiện có. Bootstrap từ chối host ngoài `db`, `localhost` hoặc loopback và không xóa database. Đây chỉ là tiện ích phát triển; môi trường triển khai phải được provision riêng, không dùng credential local trong `.env.example`.
- File volume `document-files` được mount tại `DOCUMENT_STORAGE_ROOT`, độc lập với Core `pgdata` và RAG index. Compose không map cổng Document ra host và không thêm gateway route.

## Chạy local

Từ repository root, sao chép `.env.example` thành `.env` nếu cần thay giá trị local, sau đó chạy:

```sh
docker compose --profile document up -d --build document
docker compose --profile document ps
```

Compose chạy lần lượt local DB bootstrap, migration và service. Health routes nội bộ: `/health/live` và `/health/ready`. Dừng service mà không xóa dữ liệu:

```sh
docker compose --profile document stop document
```

Không dùng `docker compose down -v` nếu cần giữ local database hoặc file volume.

## Storage contract

- `storage_key` là khóa POSIX tương đối do backend tạo; không phải tên file upload. Adapter từ chối absolute/drive/UNC paths, `.`/`..`, backslash, tên Windows dành riêng và symlink.
- `write(key, source)` đọc stream đầu vào theo chunk tới EOF, không đóng stream của caller, trả byte count và SHA-256 khi hoàn tất. Temporary file nằm cùng thư mục/filesystem với object, được tạo exclusive bằng `O_EXCL`; operation chỉ cleanup file sau khi đã tạo nó thành công, nên temp-name collision không xóa/sửa file có sẵn. File được flush + `fsync`, rồi hard-link nguyên tử không ghi đè object đã có. Duplicate final key trả `ObjectAlreadyExists`, kể cả khi nội dung trùng; caller có thể so metadata để reconcile retry.
- `open_read` trả stream do caller sở hữu và caller phải đóng. `metadata` stream lại object để tính size/checksum; `exists` trả false khi thiếu. `open_read`/`metadata` ném `ObjectNotFound` khi thiếu. `delete` trả true khi xóa và false nếu đã thiếu, nên gọi lặp an toàn.
- Lỗi path/key, xung đột immutable key, truy cập không an toàn và lỗi lưu trữ có các exception type riêng; message không chứa đường dẫn tuyệt đối. Adapter không xác thực MIME, malware, quyền nghiệp vụ hay upload policy.
- Khi write thành công, file data đã được `fsync` trước atomic finalization. Adapter không `fsync` directory và không cam kết object name sống qua power loss; điều đó phụ thuộc filesystem/runtime. Nếu final object đã được link nhưng cleanup temporary file lỗi, `write` vẫn trả `StorageMetadata` thành công, phát warning không kèm path và giữ final object; stale temp được liệt kê để reconciliation. Retry cùng key sẽ báo `ObjectAlreadyExists`.
- `list_stale_temporary_objects` chỉ nhận diện và trả khóa tương đối + thời điểm sửa. Nó không xóa object; reconciliation phải được phối hợp với database/application layer theo DOC-OD-09.
- Symlink checks chặn symlink escape đã tồn tại và final-file symlink bằng no-follow open khi OS hỗ trợ. Threat model dựa trên volume riêng chỉ ghi bởi Document UID; adapter chưa chống một tiến trình cùng UID chủ động thay parent directory giữa các syscall.

## Python checks

Chạy từ `services/document` sau khi cài package/dependencies:

```sh
python -m pip install -e ".[dev]"
ruff check src tests migrations
ruff format --check src tests migrations
python -m pytest tests -q -W error -p no:cacheprovider
```

Đặt `DOCUMENT_DATABASE_URL` trước khi chạy Alembic. Sinh SQL offline không kết nối DB; nâng cấp trực tiếp chỉ dùng một PostgreSQL Document local/test riêng.

```powershell
$env:DOCUMENT_DATABASE_URL = "<PostgreSQL URL riêng của Document>"
python -m alembic upgrade head --sql
```

PostgreSQL integration tests chỉ chạy với một database riêng có tên bắt đầu `test_document_`, role `lumi_document_test_<suffix>` và database comment marker `lumi-document-test-disposable:v1`. Bootstrap và destructive-test URLs từ chối toàn bộ query parameters; runtime database URL contract vẫn giữ nguyên. Tests xác minh current database/user, owner, ACL, marker và role attributes trên chính connection trước khi tạo/xóa schema `document`; teardown lặp lại guard ngay trước DROP. URL có driver khác, query, sai prefix/role/host, user superuser/elevated, thiếu disposable marker hoặc thiếu opt-in đều fail closed trước DROP.

Khi có `DOCUMENT_TEST_DATABASE_URL`, bắt buộc đặt `DOCUMENT_ALLOW_DESTRUCTIVE_TESTS=true`, `DOCUMENT_TEST_DATABASE_DISPOSABLE=true` và `DOCUMENT_TEST_ALLOWED_HOSTS` là allowlist chính xác cho disposable PostgreSQL hosts. Cũng phải cung cấp `CORE_TEST_DATABASE_URL` tới một test DB riêng có marker `lumi-core-test-disposable:v1`, cùng `UNRELATED_TEST_DATABASE_URL` cho role thường không có quyền CONNECT vào Document DB. CI workflow tạo các identity/database synthetic theo từng run và chỉ allow `localhost`. Không dùng SQLite hoặc database vận hành.

Fixture xác minh identity/owner, comment marker `lumi-document-test-disposable:v1`, role non-superuser/no memberships, ACL không cấp cho PUBLIC, database name prefix và các URL riêng trước mỗi DROP; teardown lặp lại cùng guard. Nếu chưa set URL, module PostgreSQL được skip; nếu URL có nhưng thiếu opt-in hoặc một identity/marker thì test fail closed thay vì skip. `bootstrap_database` không thể kết nối remote host, yêu cầu local provisioning opt-in, không ALTER owner hay reset password; role/dB hiện hữu sai state bị từ chối. CI gọi bootstrap hai lần để kiểm idempotency.

Chỉ database mới được tạo trong đúng lần gọi bootstrap hiện tại mới nhận marker disposable. Database đã tồn tại phải mang marker chính xác; thiếu hoặc sai marker sẽ fail closed dù database rỗng. Nếu provisioning bị ngắt sau khi tạo database nhưng trước marker, cần administrator reconciliation; bootstrap không tự gắn marker khi chạy lại và không drop database để rollback.

```powershell
$env:DOCUMENT_DATABASE_URL = "<Document PostgreSQL test URL>"
$env:DOCUMENT_TEST_DATABASE_URL = $env:DOCUMENT_DATABASE_URL
$env:DOCUMENT_ALLOW_DESTRUCTIVE_TESTS = "true"
$env:DOCUMENT_TEST_DATABASE_DISPOSABLE = "true"
$env:DOCUMENT_TEST_ALLOWED_HOSTS = "<verified disposable PostgreSQL host>"
$env:CORE_TEST_DATABASE_URL = "<separate Core test PostgreSQL URL>"
$env:UNRELATED_TEST_DATABASE_URL = "<unrelated non-superuser URL to the Document test DB>"
python -m pytest tests/integration -q -W error -p no:cacheprovider
```

`DOC-OD-09` vẫn mở: foundation không có deletion job, orphan cleanup, retention policy hoặc hard-delete worker. Adapter chỉ dọn file tạm thuộc lần ghi đang chạy; stale temp chỉ được liệt kê để reconciliation sau này.
