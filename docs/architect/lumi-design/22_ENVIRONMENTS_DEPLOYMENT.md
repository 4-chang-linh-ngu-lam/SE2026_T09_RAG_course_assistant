# PHẦN B — KIẾN TRÚC TRIỂN KHAI, HẠ TẦNG VÀ CẤU HÌNH MÔI TRƯỜNG

**Mã:** LUMI-DEP-002 · **Trạng thái:** `CODE-GROUNDED + PROPOSED` phải đọc theo từng mục.  
**Mốc đối chiếu:** `55324dc` ngày 31/10/2026; không sử dụng tài liệu này làm bằng chứng trạng thái runtime tại thời điểm đọc khác.

## B1. Định nghĩa ba kiến trúc cần tách biệt

1. **Kiến trúc chức năng**: hệ thống gồm các thành phần chịu trách nhiệm nghiệp vụ nào. Dùng bản đồ năng lực A02 và component A05.
2. **Kiến trúc logic theo tầng**: dữ liệu đi qua Presentation, Proxy, Application, Persistence, Operations thế nào. Dùng A03.
3. **Kiến trúc triển khai thực tế**: tại mỗi môi trường có những runtime/host/volume/network nào, có lỗi gì thì bị ảnh hưởng đến đâu. Dùng A06–A09. Không dùng mô hình `Kubernetes + Redis + RabbitMQ` chỉ vì muốn sơ đồ nhìn “enterprise”.

## B2. Sơ đồ triển khai local — Docker Compose

![A06 - Triển khai tại máy phát triển](diagrams_arch/A06_Deployment_Local.png)

### B2.1. Bảng triển khai `compose.yaml` đã đối chiếu

| Đơn vị | Image / command | Cổng | Phụ thuộc trước startup | Dữ liệu bền vững | Ghi chú an toàn |
|---|---|---|---|---|---|
| `db` | `postgres:16-alpine` | Host `127.0.0.1:5432` (cấu hình được) | Không | Docker volume `pgdata` | Health `pg_isready`; password local mẫu không dùng production |
| `migrate` | Core image, `python -m alembic upgrade head` | Không public | `db` healthy | DB | `read_only`, `tmpfs`, drop capabilities; restart no |
| `core` | Core FastAPI image | Host `127.0.0.1:8000` | `db` healthy, `migrate` success | DB | Health `/health/ready`; `read_only`, non-root image theo docs |
| `notification-worker` | Core image, `python -m app.background_worker` | Không public | `db` healthy, `migrate` success | DB + SMTP | Worker chung notification và staff-credential delivery |
| `web` | Next.js build `apps/web` | Host `127.0.0.1:3000` | `core` healthy | Không phải DB nghiệp vụ | Live adapter, `CORE_API_URL=http://core:8000` |

**Quan trọng:** bảng chỉ phản ánh file Compose, không chứng minh Docker đang chạy trên máy của người đọc. Cổng `127.0.0.1` chỉ giới hạn truy cập từ host; khi triển khai qua reverse proxy public cần thiết kế TLS, ingress, network rules và domain riêng. `db` và `migrate` không phải microservices nghiệp vụ.

### B2.2. Chuỗi khởi động và điều kiện thành công

1. Docker tạo volume và DB; đợi `pg_isready` healthy.
2. Job Alembic chạy `upgrade head`; nếu migration fail, không được khởi động Core ứng dụng với schema lệch.
3. Core khởi động, readiness `/health/ready` kiểm tra DB usable và schema; liveness `/health/live` chỉ xác nhận process sống.
4. Web chạy khi Core healthy; browser gọi `/api/v1` trên cùng origin với Web, không gọi SQL.
5. Worker claim sự kiện theo transaction; nếu có SMTP cấu hình hợp lệ mới gửi staff invitation/recovery.
6. Các thay đổi env/secret phải được đồng bộ cho Core API và worker dùng chung secret/token semantics.

### B2.3. Runbook mẫu local — không phá dữ liệu

```bash
# 1. Đứng ở root monorepo, xem trước cấu hình
cp .env.example .env                   # chỉ khi chưa có .env
# 2. CHỈNH trước khi chạy: SECRET_KEY và INTERNAL_SERVICE_SECRET >= 32 ký tự,
#    DATABASE_URL/POSTGRES_* nhất quán, COOKIE_SECURE=false chỉ local HTTP.
docker compose config --quiet
# 3. Build, chạy, đợi health; KHÔNG xóa volume sẵn có
docker compose up --build -d --wait
# 4. Xác minh
docker compose exec -T core python -m alembic check
curl -fsS http://localhost:8000/health/live
curl -fsS http://localhost:8000/health/ready
curl -I http://localhost:3000/
# 5. Xem trạng thái và log đã redacted
docker compose ps
docker compose logs --tail 100 core notification-worker
```

Các lệnh minh họa trên là **runbook đề xuất để thực hiện**. Chúng không được coi là đã chạy trong lần biên soạn tài liệu này. Không chạy `docker compose down -v`, `docker volume prune`, `alembic downgrade` hoặc seed lên DB có dữ liệu chưa được xác minh.

## B3. Sơ đồ triển khai CI và quy trình test tự động

![A07 - Môi trường tích hợp liên tục](diagrams_arch/A07_Deployment_CI.png)

### B3.1. Những job thực sự có trong `.github/workflows/core-ci.yml`

| Job | Hạ tầng | Chạy gì | Evidence/giới hạn |
|---|---|---|---|
| `core-tests` | Ubuntu runner; PostgreSQL 16 service; Python 3.12 | Ruff, Alembic upgrade/check/heads, OpenAPI snapshot, pytest, coverage, public interface 100% gate, rule traceability | Artifacts JUnit/coverage/rule-evidence; xanh chỉ đúng commit được chạy |
| `web-build` | Ubuntu runner; Node 22 | `npm install`, `npm run build` | Chứng minh production build, không chứng minh mọi hành trình trình duyệt |
| `compose-smoke` | Ubuntu runner, project Compose cô lập, cổng 15432/18000/13000 | Build/start/health, migration, worker once, Web proxy 401 không session, DB outage/recovery | Smoke và recovery subset; không phải HA/capacity production |
| `core-load` | `workflow_dispatch` với flag `run_core_load`; PG16 riêng | 10 phút class-list load 100 virtual users | Chỉ Core-06 class-list; không phải full mixed-service TP-01 hoặc 358 CCU |

**Thiết kế kiểm chứng đúng:** lưu source commit, quy trình xử lý run ID, runner type, Postgres version, config pool, migration head, JUnit, `scope mismatch`, phía máy chủ p95, client p95. Không gộp client-loopback latency với phía máy chủ service time; không coi output build là bài kiểm thử E2E.

## B4. Mô hình cloud đã được báo cáo — môi trường giả lập triển khai chính thức

![A08 - Triển khai trực tuyến tại môi trường giả lập](diagrams_arch/A08_Deployment_Cloud_Mock.png)

### B4.1. Phân biệt một môi trường hoạt động và hạ tầng mục tiêu

| Vai trò | Nền tảng theo tài liệu dự án | Trạng thái | Cần xác minh khi thực nghiệm mới |
|---|---|---|---|
| Public Web | Vercel + Next.js proxy | REPORTED DEPLOYED | Deployment ID, Web origin, live data mode, browser journeys |
| Core API | Cloud Run | REPORTED DEPLOYED | Revision, image digest, health, SQL connection, concurrency settings |
| PostgreSQL | Neon PostgreSQL 16 | REPORTED DEPLOYED | DB identifier không nhạy cảm, schema head, connection safety |
| Staff email | SMTP provider đã có staging evidence | VERIFIED ON PRIOR STAGING | Sender, recipient channel, link host, received/delivered status, expiry |
| Notification worker | Core image + worker runtime theo design | PARTIAL EVIDENCE | Worker invocation/trigger/credentials/batch, inbox end-to-end |
| Production thực | Chưa có bằng chứng sẵn sàng cho dữ liệu học sinh thật | NOT APPROVED | Privacy policy, identity verification, backup, recovery, load, release acceptance |

**Lưu ý phát hành:** trong lịch sử 30/10 có image build từ working tree chưa sync source; tài liệu mới 31/10 nói PR #38 đã merge Core/Web. Vì vậy không được tự kết luận runtime hiện nay bằng đúng `55324dc`. Cần lấy image digest và source commit ở Cloud Run, đối chiếu GitHub/CI và kiểm tra thực tế trước phát hành. Các link, account và secrets production không được ghi thẳng vào hồ sơ chia sẻ công khai.

### B4.2. Luồng request thực tế cần đo trong cloud

1. Browser HTTPS → Vercel Web.
2. Browser gọi `https://<web-origin>/api/v1/*`, Next.js proxy xác định operation allowlist và kiểm tra Origin khi mutate.
3. Proxy server → Cloud Run Core qua HTTPS.
4. Core xác thực access JWT/cookie session, tìm role và trường hiện hành; sau đó truy vấn Neon PostgreSQL 16.
5. Core trả lỗi ổn định có correlation ID; Web trình bày lỗi đúng nghĩa, không chuyển sang mock.
6. Worker cập nhật inbox/SMTP theo nghiệp vụ; browser kiểm tra kết quả sau khi sự kiện thực sự được xử lý.

**Không mặc định** có private VPC, WAF, API gateway chuyên dụng, autoscaling nhiều replica, CDN cache nghiệp vụ, đọc DB replica hay DR region. Nếu các thành phần đó được chọn sau, phải có ADR, bản vẽ mới, test và quyết định chi phí/vận hành.

## B5. Kiến trúc mạng và vùng tin cậy

![A09 - Ranh giới bảo mật](diagrams_arch/A09_Trust_Boundaries.png)

| Vùng | Mức tin cậy | Tài sản | Kiểm soát phải có | Rủi ro kiểm thử |
|---|---|---|---|---|
| Browser/client | Không tin cậy | User input, token truy cập, form | Server authorization bắt buộc | IDOR, forged class_id, cached stale data |
| Web server/proxy | Tin cậy có giới hạn | Upstream URL, cookie forwarding | Operation allowlist, exact Origin, no cross-service secret | SSRF, spoofed Origin, header leakage |
| Core API | Biên authoritative | Identity, membership, role, PII, audit | JWT/session validation, scope hiện hành, transaction, error redaction | Cross-school, replay, race, 500 leak |
| Worker | Process máy chủ | Outbox, inbox, delivery secrets | Allowlist event, service secret, retry/dedup, no credentials in public logs | Delivery to wrong user, stuck retry, poison event |
| Database | Tin cậy cao | Credentials hash, audit, grades future | Connection permission, migrations, backups, data isolation | SQL injection, orphan FK, accidental delete |
| SMTP/provider | Bên thứ ba | Staff delivery only | TLS, scope recipient, no token logs, reissue/retry | Email duplicate, expired link, provider outage |

### B5.1. Biểu đồ môi trường/địa chỉ phải ghi gì?

Một bản triển khai **hoàn chỉnh** cần có: tên môi trường, vùng cloud, URL/public hostname, TCP/HTTPS port, ingress/egress, DNS, TLS termination, VPC/subnet nếu có, database port/internal network, secret store, firewall/allowlist, image digest và revision, chính sách backup, log retention. Những giá trị chưa có trong source Lumi phải được đặt là `TBD/Operator Decision`, không tự tạo subnet IP, production domain hoặc security group ID.

## B6. Ma trận môi trường chuẩn của Lumi

| Thuộc tính | Local Dev | CI Core/Web | Preview/Staging | Production Mock | Production thật |
|---|---|---|---|---|---|
| Đối tượng | Dev | CI | QA/Reviewer | Diễn tập release | Học sinh/giáo viên thật |
| DB | Compose PG16 | PG16 riêng runner | Neon staging (theo repo) | Neon mock (theo repo) | Chưa phê duyệt |
| Dữ liệu | Synthetic | Synthetic/fixture | Synthetic/staging accounts | `Lumi Mock School` | Chỉ sau policy |
| Auth | Real Core trên dev | Real tests | Live sessions | Real API, pending manual acceptance | TBD rollout |
| Email | Mock/disconnected | Fake SMTP adapter | SMTP staging đã có bằng chứng | Cần xác minh receipt | Sẵn sàng vận hành chính thức approval |
| Web | Next.js live hoặc `dev:mock` riêng | Build/test | Preview live | Vercel production live | Sau go/no-go |
| Chỉ số đo | Smoke | pytest/lint/build | Browser E2E | Browser+release verification | SLA/RPO/RTO/capacity TBD |
| Xóa dữ liệu | Không xóa volume vô cớ | DB tạo/hủy runner | Script destructive có guard | Chỉ operator cho phép | Theo runbook/retention |

## B7. Định cỡ tài nguyên và đánh giá khả năng đáp ứng tải

### B7.1. Những số **đã được định nghĩa**

- PostgreSQL 16 trong Compose và CI; `DATABASE_POOL_SIZE=5`, `DATABASE_MAX_OVERFLOW=10`, `DATABASE_POOL_TIMEOUT_SECONDS=3` ở cấu hình mẫu local.
- API Core readiness/liveness, worker; Node 22 trong Web CI, Python 3.12 trong Core CI.
- **QAS TP-01 test fixture**: 100 users đồng thời, 10 lớp, 50 học sinh/lớp, 20 tài liệu/lớp, tệp trung bình 10MB, 30 câu mỗi bài đánh giá, chạy ổn định 10 phút. Các tham số Document/Learning là target tương lai, không phải bài đo Core hiện tại.
- Core class-list benchmark lịch sử 30/10: 58.521 HTTP 200/58.521, phía máy chủ p95 ~21,84ms, client-loopback p95 ~672,04ms, 0 scope mismatch, môi trường máy chia sẻ (không đại diện production end-user SLA).

### B7.2. Những số **chưa được phép bịa**

- Cỡ VM/Cloud Run CPU/RAM, Vercel plan, Neon storage quota, autoscaling min/max, chi phí/tháng, RPO/RTO, latency ngoài Việt Nam, throughput full product hoặc 358 CCU production.
- Nguồn thiết kế cần thực nghiệm CPU/RAM, connection pool, DB locks, event lag, SMTP capacity và concurrent workflows. Không thể kết luận chỉ từ phép đo class-list đơn lẻ.

### B7.3. Quy trình đánh giá năng lực đáp ứng tải có thể tái lập

1. Xác nhận mô hình tải (lớp học, tỷ lệ login, xem feed, bình luận, import, archive, inbox; phân bố tương tác).
2. Bắt đầu 100 CCU theo Core TP-01, đo warm-up, p95/p99 server, p95 browser, error rate, DB CPU/memory/locks, queue lag.
3. Nếu yêu cầu 358 CCU vẫn có hiệu lực, xây mô hình tải riêng có phân bổ học sinh/giáo viên/Admin, không nhân kết quả 100 user bằng 3,58.
4. Theo dõi khi test 1 worker (baseline); multi-worker cần xử lý process-local idempotency/rate-limit theo Issue #20 trước khi tăng replica.
5. Đánh giá thêm production network, auth token rotation và 409 conflict khi thao tác đồng thời.
6. Chỉ đưa thông số vào bảng sizing approved sau khi đo và review.

## B8. Hai sơ đồ triển khai cần sử dụng trong báo cáo thẩm định

- **Sơ đồ “thực tại”**: Vercel → Cloud Run Core → Neon + worker/SMTP (đánh dấu phần worker chưa được xác minh), ghi commit runtime và ngày chụp bằng chứng. Không phóng đại đảm bảo sẵn sàng cao.
- **Sơ đồ “mục tiêu tương lai”**: Web + Core + Document/Learning/LI, DB riêng theo ownership; có ghi `PROPOSED`, hạ tầng/storage/message broker chưa chốt, không ép Kubernetes hay microservice đều nằm trên host riêng.

Đây là hai trang khác nhau; không dùng đường mũi tên liền từ Web đến Document khi service Document chưa có API được duyệt.