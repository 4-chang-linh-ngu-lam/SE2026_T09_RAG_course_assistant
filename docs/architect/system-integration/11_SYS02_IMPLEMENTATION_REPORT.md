# SYS-02 — Service JWT Foundation Implementation Report

**Trạng thái:** SYS-02 — LOCAL ENGINEERING ACCEPTED.
**Technical Lead acceptance:** SYS02-RV01–08 RESOLVED/ACCEPTED in local scope; SYS02-RV09 DEFERRED; AC01–09 LOCAL PASS; AC10 BLOCKED.
**Acceptance boundary:** local engineering acceptance is not full verification or deployment readiness.
**Kiểm thử server:** SERVER VERIFICATION BLOCKED — SERVER-01.
**Phạm vi:** SYS02-R2 chỉ sửa malformed temporal claims, dependency metadata, package lint CI và report; giữ nguyên kiến trúc shared package. Không triển khai CORE-04, endpoint CORE-T03, migration, commit, push, PR hoặc deploy.

## 1. Git preflight và bảo toàn worktree

| Check | Kết quả |
|---|---|
| Repository | `D:/Workplace/SE2026_T09_RAG_course_assistant` |
| Branch | `codex/rag-technical-discovery` |
| HEAD trước pull theo preflight của lượt triển khai | `27f5f6371d246f027ae4f501c083e125b7cb1961` |
| HEAD sau pull | `b3fab5c611a3587e2ec4c70e44762a58267d0d20` |
| Tiếp tục kiểm tra | `git fetch origin` thành công; `git pull --ff-only origin codex/rag-technical-discovery` báo up-to-date; HEAD và remote HEAD đều `b3fab5c611a3587e2ec4c70e44762a58267d0d20` |
| Worktree | Các thay đổi SYS-02 và Design Correction vẫn local, chưa stage/commit. Bốn tài liệu `docs/architect/core-discovery/`, `docs/problem/` và `stitch-rag-consistency.zip` được giữ nguyên; không stash/reset/clean. |

Không có thay đổi nào được đưa lên remote. Mọi file trong báo cáo này vẫn cần Technical Lead review.

## 2. Design Correction đã đồng bộ

Các quyết định CORE-CR01–04 được giữ nguyên: Admin quản lý roster; giữ `LECTURER` cùng TeachingAssignment `PRIMARY/ASSISTING`; mở rộng authorization hiện hữu; tái sử dụng Core hiện có. Tài liệu loại bỏ join-code/self-join và mô hình `OWNER`/owner-transfer không phù hợp với Business Rules A6, A8, H1. Không thay đổi permission/business logic hoặc schema.

Tài liệu Core, System Integration và Notification có ảnh hưởng đã được cập nhật để giữ traceability cho Decision/AC cũ và nêu phần superseded. Mâu thuẫn C-AC01 về public registration vẫn được giữ là quyết định mở riêng, không bị suy rộng từ CORE-CR01–04.

## 3. Contract và implementation thực tế

- Thuật toán cố định `RS256`; verifier truyền allowlist thuật toán tường minh, không lấy thuật toán từ caller.
- Claim token: `iss`, `sub` (service identity), `aud`, `scope` (danh sách), `token_type=service`, `iat`, `exp`; `nbf` là claim tùy chọn, chỉ nhận integer epoch seconds; header có `kid`.
- Signing key RSA tối thiểu 2048 bit, riêng theo service; signer nhận đường dẫn private-key file từ config, không dùng User JWT secret. Không có HTTP token-issuer endpoint.
- Verifier tra trust map theo `kid`; mỗi entry ràng buộc issuer, subject, public-key file, audiences và scopes. Có thể giữ nhiều `kid` cùng lúc trong verifier để xoay khóa; signer phát token theo `SERVICE_JWT_KEY_ID` hiện hành.
- TTL mặc định và tối đa 300 giây; clock skew mặc định và tối đa 30 giây. Verifier kiểm chữ ký, issuer, audience, subject, token type, claims bắt buộc, thời hạn, thời điểm phát hành, optional `nbf`, key ID và scope; từ chối key/issuer/service/scope không tin cậy. `nbf` được hỗ trợ như integer epoch seconds và temporal validation của PyJWT luôn bật. TypeError/ValueError/OverflowError từ temporal claims malformed được chuẩn hóa thành `InvalidServiceJwt`; `ServiceJwtConfigurationError` vẫn được giữ nguyên.
- Contract, signer, verifier, trust policy, principal và exceptions nằm trong `packages/service-auth/src/lumi_service_auth/`; package không import Core/FastAPI/ORM/database/business logic. Core adapter tại `services/core/app/common/service_jwt.py` ánh xạ Settings thành `ServiceAuthConfig`.
- FastAPI dependency nhận `Authorization: Bearer`; thiếu/sai token trả 401, thiếu scope trả 403, trust configuration thiếu/hỏng trả 503. Dependency chưa gắn vào route production. User JWT và Service JWT không được thay thế cho nhau.
- `GET /internal/v1/classes/{class_id}/access` cùng `X-Service-Key` giữ nguyên; không nới quyền, không có fallback từ JWT lỗi sang legacy key. `POST /internal/v1/authorization/check` và action registry CORE-T03 không thuộc SYS-02.

### Quyết định kỹ thuật so với đề xuất ban đầu

PyJWT đã có nhưng môi trường cài đặt ban đầu không có backend mật mã RSA (`has_crypto=False`, thiếu `cryptography`). R2 khai báo `PyJWT[crypto]>=2.10,<3` trực tiếp trong Core cho User Authentication; package shared cũng khai báo dependency crypto của riêng nó. Core pin `lumi-service-auth==0.1.0`; local/CI cài package từ monorepo path trước Core, Docker build đồng thời hai project local và runtime dùng `--no-index` từ wheelhouse. Cơ chế này không publish và không cần tải package cùng tên từ public registry. Không thêm thư viện JWT thứ hai. Local env dùng `cryptography` 50.0.2. Private key chỉ được tạo trong temporary directories của test, không đưa vào repo.

Package khai báo Python `>=3.10` (Core vẫn dùng Python 3.12), sau khi standalone install probe chứng minh interpreter mặc định Python 3.11.9 có thể cài package và dependency crypto. Package không phụ thuộc framework runtime của Core.

## 4. File thay đổi

### Application, cấu hình và kiểm thử

- `services/core/app/common/service_jwt.py` — adapter ánh xạ Core Settings vào shared package, giữ compatibility signatures nội bộ.
- `packages/service-auth/pyproject.toml`, `packages/service-auth/src/lumi_service_auth/` — package độc lập `lumi-service-auth`, API contract, signer/verifier, trust policy và typed exceptions.
- `packages/service-auth/README.md`, `packages/service-auth/tests/test_external_consumer_install.py` — hướng dẫn cài package và wheel-install/consumer smoke ngoài Core.
- `.dockerignore` — root build-context allowlist chỉ package và Core runtime files.
- `services/core/app/common/auth_dependencies.py` — FastAPI dependency xác minh Service JWT và scope.
- `services/core/app/common/config.py` — config issuer/service/key references/trust map/audience/scopes/TTL/skew.
- `services/core/pyproject.toml` — khai báo trực tiếp PyJWT cho User Authentication và pin shared package nội bộ ở version `0.1.0`.
- `services/core/tests/security/test_service_jwt.py` — unit và dependency tests với khóa RSA dùng riêng cho test.
- `.env.example`, `compose.yaml` — biến môi trường và placeholder không chứa bí mật.
- `.github/workflows/core-ci.yml` — cài package trong Core CI, chạy independent consumer test, xác minh package ở image runtime.
- `services/core/Dockerfile` — build wheels cho shared package và Core; runtime cài cả hai.
- `services/core/README.md` — hướng dẫn cấu hình và vận hành ở mức Core.

### Design và hợp đồng

- `docs/architect/core-design/00_DESIGN_STATUS.md`
- `docs/architect/core-design/01_ARCHITECTURE.md`
- `docs/architect/core-design/02_DATABASE_DESIGN.md`
- `docs/architect/core-design/03_PUBLIC_API.md`
- `docs/architect/core-design/04_INTERNAL_API.md`
- `docs/architect/core-design/05_BUSINESS_LOGIC.md`
- `docs/architect/core-design/06_SECURITY_RESILIENCE.md`
- `docs/architect/core-design/07_TESTING_ACCEPTANCE.md`
- `docs/architect/core-design/08_IMPLEMENTATION_ROADMAP.md`
- `docs/architect/core-design/09_DESIGN_CORRECTION.md`
- `docs/architect/microservices-v1/core/API_CONTRACT.md`
- `docs/architect/microservices-v1/core/FOLDER_STRUCTURE.md`
- `docs/architect/notification-design/05_BUSINESS_LOGIC.md`
- `docs/architect/system-integration/02_GATEWAY_AND_SECURITY.md`
- `docs/architect/system-integration/09_BLOCKERS_AND_OPEN_DECISIONS.md`
- `docs/architect/system-integration/08_MASTER_IMPLEMENTATION_PLAN.md`
- `docs/architect/core-discovery/00_CORE_DISCOVERY.md`
- `docs/architect/core-discovery/01_BUSINESS_RULES_RECONCILIATION.md`
- `docs/architect/core-discovery/02_AUTHORIZATION_AND_JWT_FOUNDATION.md`
- `docs/architect/core-discovery/03_REVISED_BACKLOG_AND_REVIEW_RESPONSE.md`
- Tài liệu báo cáo này: `docs/architect/system-integration/11_SYS02_IMPLEMENTATION_REPORT.md`.

`docs/problem/` và `stitch-rag-consistency.zip` là dữ liệu local chưa track, không thuộc thay đổi SYS-02 và được bảo toàn.

## 5. Kiểm thử và bằng chứng

Các lệnh dưới đây chạy local; không chạy full suite, Docker image build hoặc server tests.

| Lệnh | Exit | Kết quả |
|---|---:|---|
| `rtk proxy .venv/Scripts/python.exe -m pytest tests/security/test_service_jwt.py tests/test_common.py tests/classroom/test_contract.py -q -p no:cacheprovider -W error` (workdir `services/core`) | 0 | 124 passed in 6.07s trên PyJWT 2.15.1; bao gồm malformed temporal claims và Core/User JWT regressions. |
| Cùng targeted file với `-k "invalid_temporal_claim_types or non_finite_temporal_claims or fastapi_dependency_returns_401 or not_before_claim"` trên PyJWT 2.13.0 | 0 | 29 passed, 41 deselected in 1.44s; chỉ PyJWT trong Core venv tạm đổi và đã restore về 2.15.1. |
| `rtk proxy .venv/Scripts/python.exe -m pytest ../../packages/service-auth/tests -q -p no:cacheprovider -W error` (workdir `services/core`) | 0 | 1 passed in 2.57s; wheel consumer chạy ngoài Core. |
| `rtk proxy .venv/Scripts/python.exe -m pip install --dry-run --no-index --no-build-isolation -e '.[dev]'` sau local path install package | 0 | Core dependency resolution thành công không truy cập index; `lumi-service-auth==0.1.0` được thỏa bởi bản cài nội bộ. |
| `rtk proxy services/core/.venv/Scripts/python.exe -m pip wheel --no-cache-dir --wheel-dir <temp> packages/service-auth services/core` (workdir repo root) | 0 | Resolver build cả hai project từ local source; Core wheel METADATA có `Requires-Dist: PyJWT[crypto]<3,>=2.10` và `Requires-Dist: lumi-service-auth==0.1.0`. Không fetch candidate same-name package từ public index. Temp wheelhouse/build metadata đã dọn. |
| `rtk proxy .venv/Scripts/ruff.exe check --config pyproject.toml app/common/auth_dependencies.py app/common/config.py app/common/service_jwt.py tests/security/test_service_jwt.py ../../packages/service-auth/src/lumi_service_auth ../../packages/service-auth/tests` | 0 | All checks passed. |
| `rtk proxy .venv/Scripts/ruff.exe format --check --config pyproject.toml app/common/auth_dependencies.py app/common/config.py app/common/service_jwt.py tests/security/test_service_jwt.py ../../packages/service-auth/src/lumi_service_auth ../../packages/service-auth/tests` | 0 | Tất cả file kiểm tra đã format. |
| `rtk docker compose config --quiet` | 0 | Compose config hợp lệ; không build hoặc khởi động container. |
| Parse `.github/workflows/core-ci.yml` bằng PyYAML | 0 | YAML hợp lệ. |

Security tests bao phủ malformed `iat`/`exp`/`nbf` dạng list/dict/null/boolean, NaN/±Infinity, lỗi FastAPI thành 401, optional `nbf` integer hợp lệ và future `nbf` bị từ chối. Test keys được sinh trong temp directories; không dùng production key hoặc dữ liệu người dùng.

## 6. SYS02-RV01–09 response

Technical Lead chấp thuận SYS02-RV01–08 trong phạm vi local implementation/review; SYS02-RV09 deferred. Các status row dưới đây giữ lại loại bằng chứng (local/deferred) và blocker vận hành tương ứng.

| Review ID | Resolution | Code Evidence | Test Evidence | Status | Remaining Blocker |
|---|---|---|---|---|---|
| SYS02-RV01 — Shared Service Auth | Tách contract, claims, trust policy, signer/verifier, principal và exceptions sang package cài độc lập `lumi-service-auth`; Core chỉ giữ Settings adapter/FastAPI dependency. Cập nhật local/CI/Docker instructions, Docker context whitelist và wheel build. | `packages/service-auth/pyproject.toml`; `packages/service-auth/src/lumi_service_auth/service_jwt.py`; `services/core/app/common/service_jwt.py`; `.github/workflows/core-ci.yml`; `services/core/Dockerfile`; `.dockerignore`. Package không import `app`, ORM, DB hoặc FastAPI. | Wheel consumer test pass; editable package install pass; isolated Python 3.11 venv cài package và dependencies, consumer import ngoài Core pass. | RESOLVED LOCALLY | Future service owners cần cài package và dùng config/key policy đã duyệt; chưa migrate consumer. |
| SYS02-RV02 — Security invariants | Enforce RS256 allowlist; bind `kid`→public key/issuer/sub; allowed scopes theo từng caller; audience và claim type; max TTL 300 giây; skew ≤30 giây; unknown/removed key reject. Không mở rộng scope. | `packages/service-auth/src/lumi_service_auth/service_jwt.py`; Core adapter/dependency tại `services/core/app/common/service_jwt.py`, `auth_dependencies.py`. | `services/core/tests/security/test_service_jwt.py`: invalid algorithm/signature/issuer/audience/sub, invalid/missing claims, caller scope escalation, lifetime/future issue time, old/new/removed/unknown key, User JWT, X-Service-Key isolation và no-token-echo. | RESOLVED LOCALLY | Key provisioning/rotation trên Testing chưa được xác minh; chưa có route consumer để integration-test. |
| SYS02-RV03 — Design Correction | Đối chiếu CR01–04 và trace D03/D04; giữ Admin roster, Lecturer assignment PRIMARY/ASSISTING; bỏ join/self-join/OWNER-transfer không phù hợp; đồng bộ database, public/internal API, business logic, AC, roadmap và contracts liên service. Không sửa Business Rules. CORE-00 vẫn `DISCOVERY APPROVED, CLOSED`. | `core-design/00_DESIGN_STATUS.md:30–36`, `01_ARCHITECTURE.md:3–9`, `02_DATABASE_DESIGN.md:3–20`, `03_PUBLIC_API.md:15–25`, `04_INTERNAL_API.md:1–9`, `05_BUSINESS_LOGIC.md:1–14`, `07_TESTING_ACCEPTANCE.md:27–29`, `08_IMPLEMENTATION_ROADMAP.md:1–11`; `core-design/09_DESIGN_CORRECTION.md`; `core-discovery/00_CORE_DISCOVERY.md:3,198`, `01_BUSINESS_RULES_RECONCILIATION.md`; `system-integration/02_GATEWAY_AND_SECURITY.md`, `08_MASTER_IMPLEMENTATION_PLAN.md`, `09_BLOCKERS_AND_OPEN_DECISIONS.md`; `notification-design/04_INTERNAL_API.md`, `learning-design/04_INTERNAL_API.md`; Core API/FOLDER docs. | Diff/static trace; không có thay đổi business permission hay schema. | RESOLVED; C-AC01 OPEN DECISION PRESERVED | C-AC01 registration conflict vẫn cần TL resolution; đây là finding ngoài CR01–04. |
| SYS02-RV04 — Verification | Chạy package installation, Ruff, format, external consumer test, targeted Core regressions, wheel metadata/dependency resolution và Compose config. Không chạy full suite/Docker build/integration local. | `packages/service-auth/pyproject.toml`; `services/core/pyproject.toml`; workflow/Core Dockerfile/Compose build context đã cập nhật. | Local command/exit/result ghi ở mục 5; 124 Core targeted tests, 29 malformed-claim regressions trên PyJWT 2.13.0 và 1 external consumer test pass. | LOCAL TARGETED VERIFICATION PASS; AC10 BLOCKED | SERVER-01: Testing SSH endpoint/fingerprint chưa xác minh; full suite/Docker build/integration phải chờ. |
| SYS02-RV05 — Report, acceptance coverage và scope gates | Báo cáo này ghi package packaging, code/test evidence, đủ AC01–10, blockers và các thao tác bị loại khỏi phạm vi. Không stage/commit/push/PR/merge/deploy; không CORE-04/T03, migration hoặc RAG app changes. | Báo cáo mục 1–9; `git status`/diff của branch; application changes giới hạn trong Core auth adapter/config/dependency, package, test/build/docs. | `git diff --check` exit 0; report và R2 delta bundle cập nhật; không có test full-system. | RESOLVED LOCALLY | Cần TL Engineering Review; SERVER-01 tiếp tục chặn full verification. |
| SYS02-RV06 — Malformed temporal claims | Bọc PyJWT `TypeError`/`ValueError`/`OverflowError` khi decode token thành `InvalidServiceJwt`; giữ `ServiceJwtConfigurationError` nguyên trạng. Optional `nbf` được hỗ trợ, chỉ integer epoch seconds và PyJWT time validation luôn bật. | `packages/service-auth/src/lumi_service_auth/service_jwt.py`; `services/core/app/common/auth_dependencies.py` map invalid token → 401 và configuration error → 503. | iat/exp/nbf list/dict/null/boolean, NaN/±Infinity; FastAPI 401 cases; PyJWT 2.13.0 targeted 29 passed. | RESOLVED LOCALLY | Full integration trên Testing vẫn bị SERVER-01 chặn. |
| SYS02-RV07 — Dependency metadata | Core khai báo PyJWT trực tiếp và pin `lumi-service-auth==0.1.0`; local/CI cài package qua đường dẫn repo trước Core, Docker wheel command nhận cả hai source local và runtime cài wheelhouse offline. | `services/core/pyproject.toml`; `.github/workflows/core-ci.yml`; `services/core/Dockerfile`; `compose.yaml`; package `pyproject.toml`; README install instructions. | Wheel METADATA có Requires-Dist cho PyJWT và lumi package; no-index Core dry-run pass sau local install; resolver xây wheel từ local source, không tải same-name package từ public registry. | RESOLVED LOCALLY | Không publish package; consumer services chưa migrate. |
| SYS02-RV08 — Shared package CI lint | Mở rộng Core CI Ruff check và format check sang shared package `src` và `tests`, không đổi RAG workflow. | `.github/workflows/core-ci.yml` Core lint step. | Ruff check/format local bao phủ package src/tests; CI YAML parse thành công. | RESOLVED LOCALLY | Remote CI chưa chạy vì không có push theo stop condition. |
| SYS02-RV09 — Deferred provisioning | Report nêu rõ chưa tạo/mount/provision key trên runtime; rotation cần deploy/restart/reload quy trình config; consumer rollout còn pending. | `services/core/README.md`; mục 8 của report này; không có thay đổi Secret Manager/deployment config. | Review tài liệu và diff; không tạo hoặc kiểm tra production key. | DEFERRED — ACCEPTED | Chờ vận hành/owner phê duyệt key mount, rotation procedure và caller rollout. |

## 7. Acceptance Criteria SYS02-AC01–10

Trạng thái acceptance cuối: AC01–09 LOCAL PASS; AC10 BLOCKED bởi SERVER-01. Đây không phải full-system verification hoặc xác nhận deployment readiness.

| AC | Trạng thái | Bằng chứng / giới hạn |
|---|---|---|
| SYS02-AC01 — ký và xác minh Service JWT | VERIFIED local | RS256 signer/verifier và valid token test; `service_jwt.py`, `test_service_jwt.py`. |
| SYS02-AC02 — phân biệt User JWT và Service JWT | VERIFIED local | `token_type=service`, identity trust binding và bài test từ chối User JWT. |
| SYS02-AC03 — enforce issuer, audience, identity, scope | VERIFIED local | Trust map theo `kid`, issuer/subject/audience/scope; bài test claim sai và scope thiếu. |
| SYS02-AC04 — từ chối token lỗi/hết hạn | VERIFIED local | Test malformed claims/headers; temporal iat/exp/nbf type errors và NaN/±Infinity; expired/future values; PyJWT 2.13.0 decoder exceptions chuẩn hóa thành 401 qua dependency. |
| SYS02-AC05 — private key không hardcode/commit/log | VERIFIED by code review | Chỉ nạp key từ file được cấu hình; không có key trong repo/log; test key ở thư mục tạm. Chưa provision key môi trường. |
| SYS02-AC06 — hỗ trợ key rotation | VERIFIED local | Trust map nhận đồng thời nhiều `kid`; test xác minh khóa cũ/mới. Runbook và đổi khóa trên môi trường chưa làm. |
| SYS02-AC07 — legacy auth không bypass endpoint mới | VERIFIED at dependency boundary | Dependency mới chỉ nhận Bearer Service JWT, không nhận `X-Service-Key`; legacy route không đổi. Chưa có route CORE-T03 để kiểm tra tích hợp route. |
| SYS02-AC08 — không regression User Authentication | VERIFIED targeted local | 124 test pass gồm Service JWT, `tests/test_common.py` và classroom contract. Không phải full suite. |
| SYS02-AC09 — hướng dẫn dùng foundation | VERIFIED local | Package README nêu cài local/consumer, Core CI và Docker packaging; independent wheel consumer test pass. Từng service chưa được migrate. |
| SYS02-AC10 — full verification trên Testing hoặc ghi BLOCKED | BLOCKED | Server Testing không xác minh được qua SSH; xem mục 8. Không chạy full suite/Docker build/integration trên Production hoặc máy local. |

## 8. Security review và blockers

- **Đã kiểm tra:** thuật toán allowlist; subject không được tin chỉ từ HTTP header; verifier ràng buộc issuer/subject/key/audience/scope; TTL/skew có giới hạn; không dùng User JWT key; exception không chứa token/key; không có logging/print trong shared package (source scan không có kết quả), không có private-key PEM marker trong implementation/test source. Test xác nhận lỗi không phản chiếu token.
- **Chưa cấu hình:** chưa mount/provision private/public service keys, issuer/trust map/service identity trên môi trường thật; không tạo production keys, Secret Manager entry hay thay secret.
- **Rotation runtime:** config Settings được đọc khi process khởi động; thay trust map, key ID, hoặc key-file reference cần restart/redeploy process. Runbook xác định thêm public key trước, rollout verifier, switch signer và giữ overlap ít nhất TTL+skew rồi mới retire key vẫn chưa được triển khai/test.
- **Consumer rollout pending:** chưa migrate service caller nào; CORE-T03 route và legacy-key retirement vẫn ngoài SYS-02-R2. Package test không thay thế rollout/integration xác thực thật.
- **Design open item giữ nguyên:** C-AC01 public registration conflict; không sửa Business Rules ngoài quyết định CORE-CR01–04.

### SERVER-01

- Port 1790, `BatchMode` + `StrictHostKeyChecking=yes`: connection reset từ `49.12.8.39`; exit 1.
- Port 1407: SSH host key changed, endpoint báo `SHA256:Jx/UwqXnoj7LMxM/F764ITvw7PzDG1rxIG6sferapsM` khác dữ liệu đã tin cậy; strict checking từ chối, exit 1.
- Không bỏ qua host-key checking, không sửa `known_hosts`, không thử cổng khác và không truy cập Production.

**Blocker:** cần Testing endpoint hoạt động và fingerprint được xác nhận qua nguồn quản trị CKEY trước khi chạy full test, Docker build hoặc integration test.

## 9. Git diff và stop condition

R1 baseline là HEAD `b3fab5c611a3587e2ec4c70e44762a58267d0d20`. So với nội dung SYS-02-review-bundle.zip/R1, R2 thay 7 file: shared verifier, security tests, Core dependency metadata, Core CI, hai README và report. R2 delta bundle: `D:/Workplace/SYS-02-R2-review-delta.zip`; ZIP chỉ chứa các file thay trong R2, diff so với R1 và test evidence mới.

Toàn bộ R1/CORE-00 diff và file local chưa track đã được giữ nguyên. `git diff --check` exit 0. `docs/problem/` và `stitch-rag-consistency.zip` không bị sửa hoặc đóng gói. Finalization task riêng cho phép ba commit và push đúng branch; không bao gồm deploy, CORE-04, CORE-T03 hoặc thay đổi RAG application. SERVER-01 tiếp tục chặn full suite/Docker build/integration.

**Trạng thái:** SYS-02 — LOCAL ENGINEERING ACCEPTED. Full verification vẫn BLOCKED — SERVER-01.
