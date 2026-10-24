# Document service — cấu trúc triển khai

**Gói đã được người dùng duyệt ngày 2026-10-23, backend và sáu workspace Web live đã triển khai.** Ownership: Document, không phải module nội bộ Core.

```text
services/document/
  pyproject.toml
  Dockerfile
  alembic.ini
  README.md
  app/
    main.py                 # API lifecycle và health
    config.py               # server-only settings
    db.py                   # document schema/role, không Core SQL
    models.py               # file/version/grant/note/bookmark/job/outbox/receipt
    schemas.py              # wire DTO, strict validation
    auth.py                 # Core identity + class HTTP client
    storage.py              # bounded staging/atomic immutable file store
    processing.py           # extractor dispatch + limits
    worker.py               # durable job claims/leases + outbox delivery
    documents.py            # owner library/version publication
                            # documents.py also owns current class source/grant operations
    personal.py             # owner notes/bookmarks + quote redaction
    events.py               # ID-only event journal/envelope
    routes.py               # reviewed public/internal allowlist
  migrations/
    env.py                  # document-only metadata/schema/version table
    versions/               # append-only new revisions
  tests/
    conftest.py             # isolated PG and bounded Core HTTP test double
    test_document_service.py # five real formats, permissions, personal history, worker/outbox
    test_core_gateway.py    # actual HTTP status/response handling
  scripts/
    configure-local.ps1    # private local env provisioning and optional Compose startup
    test-service.py        # disposable PG/schema/volume + optional Core regression suite
```

Web: giữ feature `apps/web/src/features/document`, adapter port/domain DTO trong `src/lib`, thêm client/decoder/proxy allowlist Document trong `src/lib/api`; route `/api/document/v1` riêng, không bypass Core auth/session. Không import fixtures hoặc gọi fetch nghiệp vụ trực tiếp từ feature. Test integration dùng DB/storage/actors synthetic riêng và có cleanup; không commit dữ liệu riêng tư.

Compose/migration bootstrap là shared deployment và cần review TV4. API/core notifications intake là Core.Notification và cần migration/contract riêng như [EVENT_CONTRACT](EVENT_CONTRACT.md), không chuyển bảng Document sang Core.
