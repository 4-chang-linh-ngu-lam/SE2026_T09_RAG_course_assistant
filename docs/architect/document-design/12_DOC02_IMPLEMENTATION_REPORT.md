# DOC-02 — Storage Abstraction and Local File Storage Report

**Trạng thái:** DOC-02 — LOCAL ENGINEERING ACCEPTED; SERVER VERIFICATION BLOCKED.
**Baseline:** `923b33fece83a2ef19482cd08e0ef6a3bfde8ace` · branch `codex/rag-technical-discovery`.
**Nguồn thiết kế:** DOC-D07 và DOC-T02 trong `docs/architect/rag-design/00_DESIGN_STATUS.md`.
**Giới hạn:** Chỉ LocalFileStorage; không API upload/download, auth, MIME policy, scanner, AI client/worker, object-store adapter hoặc cleanup worker.
**Review state:** DOC-02-R1 LOCAL ENGINEERING ACCEPTED; DOC02-RV05/RV06 RESOLVED; DOC02-RV07 DEFERRED. DOC02-AC01–11 LOCAL ACCEPTED; AC12 BLOCKED bởi SERVER-01.
Các AC DOC-02 không phải nghiệm thu 48 DOC-T06 Acceptance Criteria toàn Document.

## 1. Storage abstraction

`document_service.storage.interface` chỉ phụ thuộc Python standard library. Contract gồm `write`, `open_read`, `metadata`, `exists`, `delete` và khả năng liệt kê stale temporary objects; không import FastAPI, SQLAlchemy, Core hoặc DB configuration.

- `write(key, source)` mượn input stream nhưng không đóng; đọc theo chunk tới EOF và trả `size_bytes`/SHA-256.
- `open_read(key)` trả binary stream do caller sở hữu; caller phải đóng.
- `metadata` stream lại file để tính size/checksum; không nạp toàn object vào RAM.
- `exists` trả `False` nếu thiếu; `open_read`/`metadata` báo `ObjectNotFound`; `delete` trả `False` nếu thiếu và `True` khi xóa, nên delete lặp an toàn.
- Duplicate key báo `ObjectAlreadyExists`, không ghi đè kể cả khi payload bằng nhau. Caller phải kiểm tra metadata để reconcile retry.
- Lỗi invalid key, object missing/conflict, security và storage I/O có exception type riêng; message không chứa absolute filesystem path.

## 2. LocalFileStorage security và completion semantics

- Key là slash-separated relative POSIX key, backend tạo; từ chối absolute/drive/UNC, backslash, traversal, component rỗng, reserved Windows name và trailing dot. `original_filename` không tham gia tạo path.
- Temp file được tạo cùng parent/filesystem với final object, mode 0600. Adapter stream/hash/count bytes, flush + `fsync` file, rồi hard-link final atomically theo semantics no-replace. Concurrent writers cùng key có đúng một winner.
- Nếu stream/write/finalization lỗi trước link, incomplete final object không được publish; chỉ temp do operation tạo được cleanup. Nếu cleanup temp lỗi sau successful link, caller vẫn nhận `StorageMetadata`, warning không chứa path được ghi, final object giữ nguyên và stale temp có thể reconciliation; retry cùng key báo conflict.
- Adapter kiểm tra symlink/root containment, dùng `O_NOFOLLOW` cho final read khi OS hỗ trợ, không đi theo symlink khi stat/delete/list. Threat model là volume private chỉ writable bởi Document UID; nó chưa chống một process cùng UID cố tình thay parent directory giữa các syscalls.
- Directory metadata không được `fsync`; implementation chỉ xác nhận file data đã `fsync` và finalization nguyên tử trong filesystem. Không tuyên bố power-loss durability; persistence qua Docker restart cần xác minh trên Testing server.
- `list_stale_temporary_objects` là read-only; chỉ trả relative key/time. Không có tự động xóa final object hoặc temp ngoài write operation. Reconciliation cần application/database ownership ở task sau.

## 3. Volume/configuration

Compose profile `document` mount volume riêng `document-files` tại `/var/lib/lumi-document`, với storage root mặc định `/var/lib/lumi-document/files`. Volume này tách khỏi Core `pgdata` và RAG index. Container chạy non-root, read-only root filesystem, chỉ volume riêng được writable; không map cổng service ra host, không gateway route.

## 4. Verification evidence

| Command | Exit | Kết quả thực tế |
|---|---:|---|
| `python -m pytest tests -q -W error -p no:cacheprovider` (`PYTHONPATH=src`) | 0 | DOC-02-R1 run: 50 passed, 13 PostgreSQL integration tests skipped trong 1.21s vì thiếu disposable URLs/explicit opt-ins; có regression cho post-publish cleanup và exclusive temp collision. Combined DOC-01-R2 run trên cùng foundation: 53 passed, 13 skipped trong 1.79s. |
| `ruff check src tests migrations` | 0 | All checks passed. |
| `ruff format --check src tests migrations` | 0 | Formatting passed. |
| `docker compose config --quiet`; `docker compose --profile document config --quiet` | 0 | Compose wiring hợp lệ; không chạy container/build. |
| Package wheel build/install target/import | 0 | `lumi_document_service-0.1.0`, 14,825 bytes; SHA-256 `cf5da67f1e36dcaba3e27def5b0301b36ab5dff6a828c8f17b2d4afa639055b5`; storage adapter import độc lập thành công. |
| Parse `.github/workflows/document-ci.yml` bằng PyYAML BaseLoader | 0 | Workflow YAML hợp lệ; GitHub Actions remote chưa chạy. |
| `git diff --check` | 0 | Không có whitespace error. |

Không build image, khởi động container hoặc kiểm thử Docker volume restart. Local unit tests dùng temporary directories và synthetic streams.

## 5. DOC02-AC01–12

| AC | Trạng thái | Evidence / giới hạn |
|---|---|---|
| DOC02-AC01 — Storage abstraction độc lập | LOCAL ACCEPTED | Interface/adapter không phụ thuộc DB, FastAPI hoặc Core; có AST regression test. |
| DOC02-AC02 — Streamed read/write | LOCAL ACCEPTED | Chunked writes, caller-owned read stream. |
| DOC02-AC03 — SHA-256 và byte count | LOCAL ACCEPTED | Tính trong stream; kiểm tra empty và multi-chunk. |
| DOC02-AC04 — Temp write/atomic finalization | LOCAL ACCEPTED | Temp cùng parent, file fsync, atomic no-replace hard-link. Power-loss durability chưa claim. |
| DOC02-AC05 — Partial write không thành final object | LOCAL ACCEPTED | Pre-publish interruption không tạo final; post-publish temp cleanup failure giữ object hoàn chỉnh và vẫn trả metadata. |
| DOC02-AC06 — Immutable key không overwrite | LOCAL ACCEPTED | Duplicate/concurrent writer regression; O_EXCL temp collision không cleanup file do operation khác tạo. |
| DOC02-AC07 — Traversal/symlink escape bị chặn | LOCAL ACCEPTED | Absolute/Windows/UNC/traversal và symlink tests. Same-UID malicious race ngoài threat model đã nêu. |
| DOC02-AC08 — Delete/existence/error semantics | LOCAL ACCEPTED | Missing/existing/delete-repeat semantics được kiểm tra. |
| DOC02-AC09 — Persistent volume config riêng | LOCAL ACCEPTED (static) | Compose có volume độc lập; runtime mount chưa kiểm chứng. |
| DOC02-AC10 — Targeted storage tests | LOCAL ACCEPTED | DOC-02-R1 ghi nhận 50 tests toàn foundation pass; combined DOC-01-R2 run ghi nhận 53 pass, trong đó có storage tests. |
| DOC02-AC11 — Cleanup boundary | LOCAL ACCEPTED | Chỉ dọn temp thuộc write; stale temp list read-only; không final-object purge. DOC-OD-09 còn mở. |
| DOC02-AC12 — Volume persistence/restart | BLOCKED — SERVER-01 | Không chạy Docker/container restart. |

## 6. Remaining blockers và diff summary

SERVER-01 chặn PostgreSQL integration và Docker volume persistence/restart. Disk quota, backup/restore, at-rest encryption, retention, orphan reconciliation và deletion completion vẫn là decisions/operations chưa chốt; không tự triển khai chúng ở DOC-02.

Diff gồm storage Protocol/DTO, LocalFileStorage, unit tests, Dockerfile, Document volume/config wiring, README và report này. Không thêm object storage dependency, public API, RAG code hoặc destructive cleanup.

## 7. DOC-02-R1 review findings

| Finding | Resolution | Evidence | Status |
|---|---|---|---|
| DOC02-RV05 — Post-publish cleanup | Atomic hard-link là commit point. Unlink temp sau publish lỗi thì write vẫn trả metadata, log warning không có path/content, final được giữ; retry cùng key không overwrite. | `storage/local.py:54–128`; `storage/interface.py:45–58`; injected-unlink test `test_storage.py:133–163`; README `:28–36` | LOCAL PASS: post-publish cleanup regression chạy thành công. |
| DOC02-RV06 — Temp ownership | Cleanup chỉ chạy sau `os.open(...O_EXCL...)` thành công. Exclusive collision không xóa file có sẵn; interrupted write dọn temp do operation tạo; concurrent writer không overwrite final. | `storage/local.py:68–115`; tests `test_storage.py:85–130,166–190` | LOCAL PASS: collision/interruption/concurrency tests chạy thành công. |
| DOC02-RV07 — Threat model | Giữ path/symlink checks; private Document volume, chỉ Document UID ghi, backend-generated keys, parent-directory TOCTOU limitation và deferred directory-FD/no-follow traversal review. Không tuyên bố chống mọi race. | `storage/local.py:43–278`; README `:28–36`; `Dockerfile:9–17`; `compose.yaml:184–206` | DEFERRED trước Production acceptance. |

R1 không thêm platform-specific syscall adapter, cleanup worker, retention hay deletion behavior. Docker volume restart acceptance vẫn BLOCKED bởi SERVER-01.

## 8. Final acceptance status

DOC-02-R1 được APPROVED — LOCAL ENGINEERING ACCEPTANCE. DOC02-AC01–11 LOCAL ACCEPTED; DOC02-AC12 BLOCKED bởi SERVER-01. DOC02-RV07 vẫn DEFERRED hardening; filesystem traversal/symlink threat-model limits được giữ nguyên. DOC-02 acceptance không đồng nghĩa toàn bộ 48 DOC-T06 Acceptance Criteria đã PASS.

Combined foundation test evidence gồm 53 passed và 13 PostgreSQL integration tests skipped. Ở lần đóng gói cuối, shell dùng Python 3.11.9 trong khi package khai báo Python >=3.12 và không có pytest/Alembic/Ruff; các tests không được chạy lại trong shell đó. Kết quả 53/13 là lần chạy R2 đã ghi nhận trước đó trên source/tests không đổi. PostgreSQL migration/ACL/concurrency, Docker build và persistent-volume restart chưa được xác minh; SERVER-01 vẫn BLOCKED. SYS-01 chưa được nghiệm thu toàn hệ thống; runtime Service JWT key provisioning/rotation còn pending; DOC-OD-09 remains OPEN.
