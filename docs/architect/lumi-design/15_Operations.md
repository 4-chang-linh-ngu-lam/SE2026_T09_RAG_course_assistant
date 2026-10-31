# DEPLOYMENT, OPERATIONS & RECOVERY DESIGN

**Mã:** LUMI-OPS-001 · **Trạng thái:** Cấu hình Core/Web đã triển khai; hướng dẫn future services/production hardening là PROPOSED.

## 1. Môi trường và nguồn cấu hình

| Environment | Mục đích | Thành phần | Quy tắc |
|---|---|---|---|
| Local dev | Phát triển cá nhân | Docker Compose Core/Postgres/worker/Web | Dữ liệu tổng hợp; không reset volume chưa kiểm tra |
| Local test/CI | Unit/integration/contract | PostgreSQL test riêng, Node tests, CI | Migration clean, test có run ID/commit |
| Preview/staging | Review browser E2E | Web Preview, Core staging, Neon staging theo repo | Dữ liệu synthetic; SMTP test chỉ account được phép |
| Production mock | Diễn tập deploy/tích hợp | Vercel + Cloud Run + Neon `Lumi Mock School` | **Không** chứa học sinh thật, chưa được gọi production-ready |
| Production thật | Vận hành trường | Phụ thuộc operator-approved runbook | Cần policy data, backup, incident, retention, capacity validation |

## 2. Runbook local (Core MVP)

**Điều kiện:** Docker Compose v2/Linux containers, Node yêu cầu theo `apps/web/README.md`, secrets local trong `.env` không commit; verify database target trước thao tác có dữ liệu.

1. Clone đúng revision/branch, kiểm tra `.env.example`, không copy secret production.
2. Cấu hình `SECRET_KEY`, internal secrets, `DATABASE_URL`, `WEB_ORIGIN`, `CORE_API_URL`, `CORS_ORIGINS`; khi HTTP localhost, `COOKIE_SECURE=false` theo Core README.
3. Chạy `docker compose config --quiet`; lỗi env phải sửa trước khi startup.
4. Khởi động PostgreSQL, chờ healthy; chạy migration job → `alembic upgrade head`, `alembic check` theo runbook.
5. Khởi động Core và worker; kiểm tra `/health/live`, `/health/ready` bằng HTTP.
6. Chạy Web live với same-origin proxy; thử login flow và API 401 khi không có phiên (đó có thể là behavior đúng).
7. Dùng guarded seed chỉ trên DB dev/test clean đã xác minh; ghi seed marker/revision, không in password/code vào log.
8. Chạy workflow Admin → Lecturer → Student, audit/outbox/inbox; tách smoke API khỏi browser E2E đầy đủ.

**Không** sử dụng `docker compose down -v`, `prune` hoặc `dropdb` với volume/database không xác minh; nếu migration fail, xem logs/snapshot trước khi thay schema.

## 3. Configuration registry

| Biến/cấu hình | Sở hữu | Mục đích / lưu ý |
|---|---|---|
| `DATABASE_URL` | Core | Kết nối schema Core, TLS theo môi trường |
| `SECRET_KEY` | Core API + worker | Chữ ký/credential delivery; phải đồng nhất và ổn định theo release |
| `INTERNAL_SERVICE_SECRET` | Core | Internal access check, giữ server-side |
| `COOKIE_SECURE` | Core | true khi HTTPS; local HTTP đặt false có kiểm soát |
| `CORS_ORIGINS` | Core | Khớp exact Web public origin |
| `CORE_API_URL` | Web server | Upstream Core, không expose credential nội bộ |
| `WEB_ORIGIN` | Web server | Exact public origin cho proxy mutation check |
| `PUBLIC_WEB_URL` | Core API/worker | Web origin trong staff invitation/recovery links |
| `SMTP_HOST/FROM/PORT/SECURITY` | Core/worker | Mail delivery staff; không cho Student self-email activation |
| `SMTP_USERNAME/PASSWORD` | Secret store | Secret provider, không commit/log |
| `TEST_DATABASE_URL` | Test harness | Chỉ PostgreSQL test riêng |

Giá trị default, bắt buộc/tùy chọn và tên đầy đủ phải được xác nhận tại `.env.example`/Pydantic settings **ở phiên bản deploy cụ thể**.

## 4. Migration/seed/bootstrap lifecycle

- **Migration:** one head theo revision; không sửa revision đã áp dụng; preflight backup; có `upgrade head`, `alembic check`, schema compatibility test.
- **School mapping:** workflow report → manifest → plan SHA → review → apply với transaction; không map người thật theo suy đoán. Nullable FK v0014 không có nghĩa school mapping tự hoàn tất.
- **Dev seed:** database name allowlist + empty preflight + random credential + marker idempotent; chạy theo runbook.
- **Production bootstrap:** operator-triggered, tách khỏi auto-start và seed dev; xác minh operator, school, first Admin, token handoff và audit. Runbook phải ghi recovery nếu invitation bị thất lạc.
- **Rollback:** DB migrations thường không thể rollback bằng redeploy đơn thuần; cần compatibility window, backup/restore tested, xác định data loss acceptable theo policy.

## 5. CI/CD release gates

| Gate | Bằng chứng yêu cầu |
|---|---|
| Source | Commit SHA, branch, PR, dependency lockfile hash |
| Backend style | Ruff lint/format, type/tests theo pipeline được cấu hình |
| Migration | Fresh database upgrade/check; drift check; downgrade chỉ khi an toàn |
| Backend tests | PostgreSQL 16, unit/integration/security/contract, counts, skips, coverage |
| Web | Node check/typecheck/test, live build, no mock fixture scan |
| Compose | Config, migrations, Core/worker/Web smoke |
| Browser E2E | Real Admin→Lecturer→Student journey, role/negative cases, no mock |
| Deployment | Image digest/source SHA, env revision, health/readiness và rollback plan |
| Security | Secret scan, auth/permission regression, no PII in logs/evidence |

Bằng chứng PR #33–#38 trong repo là lịch sử riêng của từng revision; không dùng để tuyên bố commit bất kỳ tương lai đã chạy test.

## 6. Deploy runtime hiện tại và drift

Hồ sơ `SYSTEM_DESIGN.md` ngày 31/10 ghi PR #38 đã hợp nhất Core/Web; Cloud Run từng cần redeploy từ `main` và cấu hình `PUBLIC_WEB_URL` để áp dụng email link mới. Một production image trước đó được build từ working tree chưa sync. Vì vậy mỗi lần phát hành phải xác nhận:

- Git source SHA = CI source SHA = container image provenance = runtime revision.
- `PUBLIC_WEB_URL`, `WEB_ORIGIN`, `CORE_API_URL`, `CORS_ORIGINS`, cookie flags khớp domain/HTTPS.
- Migration revision DB tương thích image và không có destructive DB seed.
- Worker cùng code/schema/secret với Core nếu dùng chung flow.
- SMTP/from/link link tới đúng Web target; credentials không lộ.

## 7. Monitoring và alerting — đề xuất

| Nhóm | Số đo tối thiểu | Alert candidate / owner decision |
|---|---|---|
| API | request counts/status/p95 by route, 401/403/409/5xx | Ngưỡng alert cần operator duyệt |
| DB | connection usage, pool timeout, migration mismatch, slow query | Cần thống nhất capacity/runbook |
| Worker | outbox pending/age, retry count, poison/quarantine events | Cần retry/SLO policy |
| SMTP | delivery pending/expired/reissue, provider errors | Không ghi mail token |
| Security | unexpected cross-school denies, last-admin attempts, rate limit | Không log PII payload |
| Browser | route crashes, API availability, failed refresh/submit | Không thu thập raw student data |
| Future Document | processing queue age, failed revisions, blob checks | Chỉ sau design approved |
| Future Learning | save ACK latency, overdue auto-submit, duplicate suppressions | Chỉ sau design approved |
| Future LI | evidence lag, stale grade correction, suppression counters | Chỉ sau design approved |

## 8. Backup/recovery

- **Chưa có RPO/RTO production được duyệt** trong nguồn chuẩn. Không tự điền “RPO 5 phút/RTO 1 giờ”.
- Cần định nghĩa scope backup: DB Core, future file blobs, future Learning grades, service keys, config, logs; loại bỏ secrets khi xuất evidence.
- Khôi phục DB phải kiểm tra schema migration, user/session revocation state, audit/outbox/notification watermark, import batch consistency.
- Khôi phục Document cần đối chiếu file checksum/version/grants, tránh mở lại nguồn đã bị revoke.
- Khôi phục Learning cần kiểm tra submission/grade version và events phát lại idempotent.
- Cần tập restore drill định kỳ có dữ liệu synthetic; ghi actual RTO/RPO, không khẳng định từ thiết kế.

## 9. Incident response

1. Nhận cảnh báo, phân loại privacy/security/availability/data integrity.
2. Ghi incident ID, service/revision/time/correlation IDs; không sao chép raw student PII vào ticket công khai.
3. Hạn chế ảnh hưởng (revoke sessions/grants, disable only affected endpoints, isolate worker) theo runbook; không tắt auth chung để khôi phục UI.
4. Khôi phục từ backup/retry có xác nhận consistency.
5. Postmortem gồm root cause, blast radius, evidence, corrective actions, regression tests và cập nhật docs/ADR.

## 10. Release checklist để operator ký duyệt

- [ ] Source-image-runtime cùng revision; migration healthy và rollback khả thi.
- [ ] Secrets/TLS/origins/cookies/SMTP verified, không ghi code vào log.
- [ ] Student test data synthetic, không lẫn với học sinh thật.
- [ ] Browser live E2E Admin→Lecturer→Student; không fallback mock.
- [ ] Current role/school/class permission tests và audit/notification smoke.
- [ ] Data-retention/identity validation trước dữ liệu thật (PENDING POLICY).
- [ ] Capacity/backup/recovery measurements có evidence.
- [ ] Không có high-severity open blocker theo release policy được duyệt.