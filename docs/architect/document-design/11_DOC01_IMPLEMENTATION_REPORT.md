# DOC-01 — Database Ownership and Schema Report

**Trạng thái:** DOC-01 — LOCAL ENGINEERING ACCEPTED. SERVER VERIFICATION BLOCKED.
**Baseline:** `923b33fece83a2ef19482cd08e0ef6a3bfde8ace` · branch `codex/rag-technical-discovery`.
**Nguồn thiết kế:** DOC-T01/T02 và DOC-D04 trong `docs/architect/rag-design/00_DESIGN_STATUS.md`; SYS-D04 trong `docs/architect/system-integration/00_DESIGN_STATUS.md`.
**Giới hạn:** Không chạy migration trực tuyến, không truy cập Production, không cài Service JWT consumer, CRUD, worker hay migration Core.
**Review state:** DOC-01-R2 APPROVED — LOCAL ENGINEERING ACCEPTANCE. DOC01-RV09/RV10 RESOLVED. DOC01-AC01–08 LOCAL PASS; DOC01-AC09/10 BLOCKED by SERVER-01.
Các trạng thái bên dưới chỉ nghiệm thu DOC-01 foundation; không suy ra 48 DOC-T06 Acceptance Criteria toàn Document đã đạt.

## 1. Thiết kế được ánh xạ

| Quyết định | Cách triển khai | Bằng chứng |
|---|---|---|
| DOC-T01 — database ownership riêng | `DOCUMENT_DATABASE_URL` độc lập; `document_service` không đọc `DATABASE_URL` hoặc import Core. Local Compose bootstrap tạo login role/database riêng trên PostgreSQL instance hiện có. | `services/document/src/document_service/config.py`, `db.py`, `bootstrap_database.py`; `compose.yaml` |
| SYS-D04 — PostgreSQL instance chung, database/credential riêng | Compose Document profile dùng service `db` hiện tại, nhưng database `lumi_document` và role `lumi_document`; có volume file riêng. Production provisioning vẫn do môi trường vận hành thực hiện. | `compose.yaml`, `.env.example`; local bootstrap chỉ chấp nhận host `db`/loopback |
| DOC-T02 — đúng bốn bảng | `documents`, `document_versions`, `document_grants`, `ingestion_jobs` trong schema `document`. Không tạo deletion job hoặc business table khác. | `services/document/src/document_service/models.py`, `migrations/versions/0001_initial_document_schema.py` |
| UUID/TIMESTAMPTZ/BIGINT/INTEGER/CHAR(64) | UUID cho ID nội bộ và Core logical IDs; timestamps timezone-aware; `size_bytes` BIGINT, version/attempt INTEGER, SHA-256 CHAR(64). Status dùng VARCHAR + CHECK. | Models và migration ban đầu |
| Integrity | Unique document/version number, storage key và idempotency key; partial unique active grant; active ingestion job duy nhất trên mỗi version; metadata bắt buộc khi file STORED. SHA-256 không unique toàn cục. | Migration constraints/indexes; tests PostgreSQL trong `tests/integration/test_postgres_schema.py` |
| Composite version pointers | `latest_version_id` và `active_rag_version_id` tham chiếu composite `(document_versions.id, document_versions.document_id)` cùng document. Migration tạo bảng trước rồi mới thêm hai FK vòng. | Model `Document`; revision `0001` |

`ai_job_id` và `index_ref` là chuỗi opaque vì external ID format thuộc contract AI còn pending. Owner, classroom, granter và revoker UUID là logical references; không có Core FK/JOIN. Các FK nội bộ dùng RESTRICT, không cascade. New ingestion attempt bắt đầu ở `attempt_number=0`; constraint chỉ chặn giá trị âm.

## 2. Database lifecycle và an toàn migration

- Alembic độc lập, version table tại `document.alembic_version`; revision `0001` có thể sinh SQL cho database mới. Schema model chỉ bao gồm bốn bảng Document.
- `Database` tạo engine/session factory lazy từ `DOCUMENT_DATABASE_URL`, dùng UTC, `pool_pre_ping`, timeout cấu hình được; `get_db()` đóng session sau request và `transaction()` commit/rollback unit-of-work rõ ràng.
- `/health/live` không phụ thuộc DB; `/health/ready` trả 503 khi URL/schema/DB chưa sẵn sàng. Không có public Document business route hoặc gateway mapping.
- Downgrade offline bị từ chối. Downgrade online chỉ tiếp tục khi bốn bảng rỗng; không xóa data đang tồn tại.
- `document-db-init` yêu cầu opt-in local/test, chỉ chấp nhận host local và identity nằm trong namespace Document. Database/role hiện hữu chỉ được dùng khi owner/attributes/membership khớp; bootstrap không đổi owner, quyền role hay password. Nó thu hồi ACL của PUBLIC và chỉ giữ quyền database cho Document owner; configured bootstrap superuser vẫn luôn bypass ACL theo PostgreSQL semantics.
- Chỉ database test được tạo trong chính lần gọi bootstrap hiện tại mới nhận disposable marker. Database test đã tồn tại phải có marker chính xác và owner/role/credential hợp lệ; thiếu hoặc sai marker fail closed kể cả khi database rỗng. Nếu lần provision bị ngắt trước khi đánh dấu, cần administrator reconciliation; không ghi đè marker, takeover/reset credential hoặc tự drop database.
- Bootstrap và destructive-test URLs từ chối query parameters. Trước mỗi `DROP SCHEMA`, test guard đọc identity, owner, marker, elevated privileges, role memberships và ACL trên đúng SQLAlchemy connection sẽ thực thi DDL; setup và teardown đều chạy guard. Alembic URL phải trùng identity đã validate.
- `.github/workflows/document-ci.yml` đã chuẩn bị PostgreSQL 16 CI với Document/Core test databases và roles riêng; workflow chưa chạy trên remote.

## 3. PostgreSQL integration tests đã chuẩn bị

Test DB phải là PostgreSQL và tên bắt đầu `test_document_`; fixture làm sạch schema `document` chỉ trong DB này, chạy migration đầu rồi kiểm tra metadata/constraints. Không có SQLite fallback.

Cases gồm migration upgrade/model drift, composite pointer FK, duplicate version/storage key, partial active grant, idempotency/active-job uniqueness, invalid status/metadata/size/version/attempt, credential/database isolation và concurrent version-number collision. Concurrent test chỉ chứng minh DB unique constraint; application-level collision handling thuộc task sau.

## 4. Verification evidence

| Command | Exit | Kết quả thực tế |
|---|---:|---|
| `python -m pytest tests -q -W error -p no:cacheprovider` (`PYTHONPATH=src`) | 0 | DOC-01-R2 targeted run: 53 passed, 13 PostgreSQL integration tests skipped trong 1.79s vì thiếu disposable URLs/opt-ins. |
| `ruff check --no-cache src tests migrations` | 0 | All checks passed. |
| `ruff format --check --no-cache src tests migrations` | 0 | 18 files already formatted. |
| `python -m alembic upgrade head --sql` với URL tổng hợp | 0 | Sinh SQL cho schema/bốn bảng, active indexes và hai composite pointer FKs; không kết nối database. |
| `docker compose --profile document config --quiet` | 0 | Compose profile hợp lệ; không chạy container/build. |
| Build wheel + cài vào temporary target + import `bootstrap_database` | 0 | `lumi_document_service-0.1.0`, 14,825 bytes; SHA-256 `cf5da67f1e36dcaba3e27def5b0301b36ab5dff6a828c8f17b2d4afa639055b5`; package import thành công. |
| Parse `.github/workflows/document-ci.yml` bằng PyYAML BaseLoader | 0 | Workflow có job `document-tests`; workflow remote chưa chạy. |
| `git diff --check` | 0 | Không có whitespace error. |

Không chạy PostgreSQL migration, constraint suite, Docker build hoặc volume test. SERVER-01 vẫn BLOCKED.

## 5. DOC01-AC01–10

| AC | Trạng thái | Evidence / giới hạn |
|---|---|---|
| DOC01-AC01 — Service/database ownership riêng | LOCAL PASS (static) | Document URL/role/database/schema riêng; ACL code giới hạn PUBLIC. ACL thật và production provisioning chưa kiểm chứng. |
| DOC01-AC02 — Đúng bốn bảng DOC-T02 | LOCAL PASS | Metadata và migration có đúng bốn bảng nghiệp vụ. |
| DOC01-AC03 — Initial migration | LOCAL PASS (static) | Offline upgrade SQL sinh thành công; chưa chạy trên PostgreSQL thật. |
| DOC01-AC04 — Constraints và indexes | LOCAL PASS (static) | Model/migration, DDL compile tests; PostgreSQL constraint acceptance chưa chạy. |
| DOC01-AC05 — Composite pointer ownership | LOCAL PASS (static) | Hai composite FK được phát sinh; real constraint test đã chuẩn bị. |
| DOC01-AC06 — Không cross-service SQL/FK/import | LOCAL PASS | IDs Core là UUID logical references; FK chỉ tới bảng trong schema Document. |
| DOC01-AC07 — Config/session lifecycle riêng | LOCAL PASS | `DOCUMENT_DATABASE_URL`, lazy engine, session/transaction helpers và health readiness; bootstrap refuses unsafe role/owner state. |
| DOC01-AC08 — PostgreSQL tests được chuẩn bị | LOCAL PASS (prepared) | Integration cases yêu cầu DB `test_document_`, `DOCUMENT_TEST_ALLOWED_HOSTS`, disposable comment marker, explicit opt-in và Document/Core/unrelated roles; chưa thực thi. |
| DOC01-AC09 — Migration/constraints trên PostgreSQL thật | BLOCKED — SERVER-01 | Không có DB migration hoặc constraint acceptance thực tế. |
| DOC01-AC10 — Isolation/concurrency/restart trên DB thật | BLOCKED — SERVER-01 | Credential/concurrency tests đã chuẩn bị; database/runtime restart chưa xác minh. |

## 6. Blockers và diff summary

SERVER-01 chặn PostgreSQL thật, migration/constraint/ACL/concurrency checks và runtime/database restart verification. Docker image build và persistent-volume restart chưa được xác minh. Production database/credential provisioning chưa được cấp; local Compose bootstrap không thay thế provisioning production. Runtime Service JWT key provisioning and rotation remain pending. DOC-OD-09 vẫn OPEN; không có `deletion_jobs`, retention/hard-delete policy hoặc cleanup worker. RAG-D02, AI ID contract và các API/service contracts khác không bị thay đổi.

SYS-01 chưa được nghiệm thu ở cấp toàn hệ thống: Core runtime identity mặc định có thể là PostgreSQL bootstrap superuser; integration two-way least-privilege và production role model chưa được nghiệm thu. Không tuyên bố REVOKE PUBLIC hạn chế PostgreSQL superuser.

R1 delta: database provisioning/ACL helper, Alembic metadata filter, PostgreSQL ACL/destructive-test fixtures, CI provisioning/skip gate, implementation report và `.gitignore` exception để Document CI workflow được track. Không sửa Core ACL/config, schema/migration, Business Rules hay Service JWT.

## 7. DOC-01-R1 review findings

| Finding | Resolution | Evidence | Status |
|---|---|---|---|
| DOC01-RV05 — Database ACL | Revoke all PUBLIC DB privileges; only verified Document owner is explicitly in ACL. Bootstrap superuser's inherent bypass is recorded. Integration checks Document connection, unrelated denial, effective grants and two-way identity. No existing Core ACL is changed; CI uses only a synthetic Core test database. | `bootstrap_database.py:120–125,265–281`; ACL integration `test_postgres_schema.py:62–159,458–519`; grant unit `test_foundation.py:363–367`; synthetic CI ACL `document-ci.yml:80–87` | Code/tests prepared; PostgreSQL NOT RUN / SERVER-01 BLOCKED. |
| DOC01-RV06 — Safe provisioning | Explicit local/test opt-in and exact namespace/URL match. Existing role attributes, membership, DB owner, grants and credentials are validated; no ALTER ROLE/password reset/owner takeover. Retry is idempotent. Helper prints no URL/password/SQL; errors are sanitized and CI masks per-run credentials. | `bootstrap_database.py:45–94,102–118,144–180,207–284`; unit tests `test_foundation.py:259–443`; CI repeats/masks `.github/workflows/document-ci.yml:55–106` | LOCAL PASS / PostgreSQL provisioning NOT RUN. |
| DOC01-RV07 — Metadata comparison | Alembic env and integration compare use identical schema/version-table filters; `alembic_version` is excluded by name only. No business table/constraint is suppressed. | `migration_config.py:4–19`; `migrations/env.py`; unit filter `test_foundation.py:40–50`; integration compare `test_postgres_schema.py:237–252` | Static configuration PASS; actual PG comparison BLOCKED. |
| DOC01-RV08 — Destructive test guard | Setup and teardown require opt-ins, PostgreSQL driver, host allowlist, test namespace/role, live current identity, DB owner/comment, non-elevated roles, no membership and no PUBLIC/unapproved grants. Both DROP operations are guarded on the same connection that executes DDL; CI rejects skipped integration tests. | Guard helpers `tests/safety_guards.py:13–139`; fixture `test_postgres_schema.py:45–210`; unit guards `test_foundation.py:183–253`; workflow `document-ci.yml:29–125`; `.gitignore:42–45` | Guard unit tests LOCAL PASS; destructive PG suite NOT RUN. |

R1 targeted suite completed: 50 local tests PASS; 13 PostgreSQL integration tests are skipped because disposable URLs/explicit opt-ins were not provided. ACL enforcement, real metadata comparison, migration, and destructive guard execution remain NOT RUN / SERVER-01 BLOCKED.

## 8. DOC-01-R2 review findings

| Finding | Resolution | Code/test evidence | Status / remaining blocker |
|---|---|---|---|
| DOC01-RV09 — Disposable database marker | A marker is written only when this bootstrap invocation observed no target database and created it. An existing test database is reusable only with the exact marker, expected owner and valid dedicated role/credentials. Missing/wrong marker fails even when empty. Interrupted provisioning requires administrator reconciliation; bootstrap neither overwrites comments nor takes over/resets credentials nor drops a database. | `bootstrap_database.py:182–199,224–240,263–282`; regressions in `test_foundation.py:554–599` cover new, marked existing, missing, wrong and inconsistent/interrupted cases. | RESOLVED — LOCAL ENGINEERING ACCEPTED; actual PostgreSQL provisioning NOT RUN / SERVER-01 BLOCKED. |
| DOC01-RV10 — Connection safety | Bootstrap and destructive-test URLs reject every query parameter. Before setup and teardown DROP, the exact connection that will execute DDL checks `current_database/current_user`, owner, disposable marker, role elevation, memberships, PUBLIC/unapproved ACLs and CONNECT. Alembic's configured test URL is identity-matched against the validated disposable URL. | `bootstrap_database.py:45–63`; `safety_guards.py:13–54,85–130`; `test_postgres_schema.py:45–120,161–207`; regression tests in `test_foundation.py:55–72,203–253,278–402,465–490`. | RESOLVED — LOCAL ENGINEERING ACCEPTED; PostgreSQL setup/teardown and actual Alembic migration NOT RUN / SERVER-01 BLOCKED. |

DOC-01-R2 targeted local run completed: `python -m pytest tests -q -W error -p no:cacheprovider` — exit 0, 53 passed and 13 PostgreSQL integration tests skipped in 1.79s. Ruff check and format check passed; offline Alembic SQL generation, `docker compose --profile document config --quiet`, and `git diff --check` passed. The packaging shell selected Python 3.11.9 although this service declares Python >=3.12, and did not have pytest/Alembic/Ruff installed. Tests were not rerun in that shell; the cited successful R2 run was captured earlier against the unchanged source/tests. Compose configuration and whitespace checks were rerun successfully. PostgreSQL migration, live ACL/concurrency verification, Docker build, volume persistence, server test, and Production access were not performed. SERVER-01 remains BLOCKED.
