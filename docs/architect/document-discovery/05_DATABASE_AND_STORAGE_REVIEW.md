# DOC-00.5 — Database và storage

## 1. Hiện trạng

Core khởi tạo SQLAlchemy engine theo DATABASE_URL; metadata dùng schema PostgreSQL core (services/core/app/common/db.py:14, 25–35). Alembic migration hiện tại kết thúc ở 0014; services/core/migrations/README.md ghi migration chỉ quản lý schema core và không có FK xuyên service. Compose root có một PostgreSQL database và volume pgdata; đây là cấu hình local cho Core, không phải Document persistence.

Không tìm thấy Document ORM, migration, database URL, database role, bucket/object storage, file volume, stream API hoặc checksum record. Không đọc dữ liệu Production. RAG giữ artifacts/index files và local SQLite registry/evaluation harness; các file này không có vòng đời hoặc quyền sở hữu Document.

## 2. Schema đã được chấp thuận trong DOC-T01/T02

DOC-T01 chọn PostgreSQL instance có thể dùng chung hạ tầng nhưng database, credential, migration riêng theo service. Cấm SQL JOIN/FK trực tiếp qua service; Core identity/classroom IDs được xác minh qua API.

DOC-T02 duyệt bốn entity Document-owned:

| Bảng mục tiêu | Trường chính theo quyết định |
|---|---|
| documents | id, owner_id, title, status, latest_version_id, active_rag_version_id, created_at, updated_at, deleted_at |
| document_versions | id, document_id, version_number, storage_key, original_filename, mime_type, size_bytes, sha256, file_status, created_at, stored_at |
| document_grants | id, document_id, classroom_id, granted_by, granted_at, revoked_by, revoked_at |
| ingestion_jobs | id, version_id, ai_job_id, idempotency_key, status, attempt_number, index_ref, next_action_at, error_code, created_at, updated_at, completed_at, lease_until, lease_token |

Quy tắc kỹ thuật được duyệt gồm UUID nội bộ, TIMESTAMPTZ, BIGINT size, INTEGER version/attempt, CHAR(64) SHA-256, CHECK constraints cho trạng thái và số dương, unique document/version_number, document/id, storage_key, idempotency_key, partial unique active grant theo document/classroom, cùng indexes theo owner/status, version, grants và jobs. Hai pointer version phải tham chiếu cùng document; FK chỉ nội bộ database Document. Đây là target, chưa có schema triển khai.

## 3. Transaction và consistency cần giữ

DOC-T02 xác định bốn ranh giới:

1. T1 hoàn tất upload: version STORED, latest pointer và PENDING job được ghi bền vững cùng transaction sau khi file được lưu.
2. T2 activate: khóa Document, xác minh job/version/index và readiness; stale result không được cập nhật active pointer.
3. T3 revoke: ghi revoke trong Document transaction; truy vấn mới bị chặn ngay, không đợi xóa index/file.
4. T4 retry: chỉ tạo execution/job/key mới khi lần trước được xác nhận FAILED và version còn đủ điều kiện.

File và PostgreSQL không nằm trong một transaction nguyên tử. Cần idempotent storage keys, checksum, outbox/reconciliation hoặc quy trình tương đương đã được review để xử lý crash giữa lưu file và commit metadata. Không tự thêm bảng/cơ chế vào thiết kế đã duyệt; nếu bốn bảng không đủ để biểu đạt durable cleanup/reconciliation, đưa lại Technical Lead xem xét.

## 4. File storage và handoff

DOC-D07 chọn trong Increment 1: Document-owned Storage Interface, Docker Volume riêng bền qua container restart, Internal Download API có service authentication, giới hạn scope theo job, streaming binary, không Base64/path vật lý, và SHA-256. AI tải đúng DocumentVersion; AI xóa file tạm của nó. Storage abstraction cho phép thay adapter object storage sau này.

Hiện compose chỉ mount pgdata. RAG artifacts trên filesystem không phải source file storage và không được chia sẻ đường dẫn nội bộ cho service khác. Chưa thấy:

- persistent Document file volume hoặc Storage Interface;
- private file naming/path traversal protection và atomic temp→final move;
- streaming download với length/type/checksum headers;
- encryption-at-rest, quota, backup/restore, orphan reconciliation;
- malware/quarantine/ZIP bomb policy và signed-link TTL.

Các mục chưa có quyết định là blockers thiết kế vận hành; không tự coi như mục tiêu đã được duyệt. DOC-D07/T03 giới hạn dung lượng, credential và endpoint cụ thể vẫn pending.

## 5. Rủi ro tương thích và migration

- Không được thêm bốn bảng vào schema Core hoặc tạo FK Document→core.users/core.classrooms.
- Không được map owner/class IDs bằng query Core DB; xác minh qua Core service contract.
- Core migration 0014 là migration của Core; không sửa revision đã áp dụng hoặc gộp Document schema vào Core Alembic history.
- Tài liệu migration Core ghi head 0014; điều này không cho biết Document database đã có dữ liệu hay chưa. Discovery không kiểm tra DB Production.
- Trước migration Document cần preflight DB riêng, schema/role ownership, backup/restore plan và guard chống kết nối nhầm DB.
- Chưa có Document DB để đánh giá mất dữ liệu hoặc migration path; mọi kết luận về Production data là NOT_VERIFIED.

## 6. Durable deletion và account deletion

CORE-T01 đề xuất account_deletion_jobs tại Core để điều phối per-target; CORE-T06/T08 yêu cầu revoke ngay, service tự xử lý dữ liệu mình sở hữu, completion chỉ sau đủ nghĩa vụ. DOC-T02 hiện chỉ có documents, document_versions, document_grants và ingestion_jobs; không định nghĩa durable deletion inbox/job.

Cần tách document deletion khỏi account deletion. Document sở hữu source file/grants; AI sở hữu derived index và temp files; Core điều phối account-level status; Notification chỉ phân phối sự kiện. Durable ACK không được coi là cleanup hoàn tất. Retry/reconciliation phải sống qua restart và idempotent; index delete phải xác nhận version/index identity và chống stale-ingestion resurrection.

Retention 14 ngày trong SYS-B07 chưa rõ áp dụng loại dữ liệu nào. Chưa quyết định persistence schema, AI completion API, retry/dead-letter, backup erasure hoặc physical purge. Ghi DOC-OD-09; không tạo migration hoặc chọn bảng trong R1.
