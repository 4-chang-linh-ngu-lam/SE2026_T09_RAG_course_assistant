# CORE-04 — Internal Authorization Adapter Implementation Report

**Trạng thái:** CORE-04 — LOCAL ENGINEERING ACCEPTED. SERVER VERIFICATION BLOCKED.
**Decisions:** CORE04-D01-A (PRIMARY approval contract) và CORE04-D02-A (Student-only PRACTICE_ACCESS) ACCEPTED.
**Git baseline:** `6e0b3e9fcc835a7475dffa398b51b7583ec39520` trên `codex/rag-technical-discovery`.
**Review:** CORE04-RV01–06 ACCEPTED trong phạm vi local engineering; RV07 RESOLVED AT CONTRACT LEVEL; RV08–09 RESOLVED; RV10 DEFERRED / SERVER-01 BLOCKED.
**Verification:** CORE04-AC01–11 LOCAL PASS; AC12 BLOCKED. Không có migration, consumer migration, RAG change hoặc full-system acceptance.

**CORE04-D01-A / CORE04-D02-A:** ACCEPTED. D01 approval actions are deferred and not registered in R1; D02 makes `PRACTICE_ACCESS` Student-only.

## 1. Git preflight và scope

- Repository: `D:/Workplace/SE2026_T09_RAG_course_assistant`; branch `codex/rag-technical-discovery`.
- Fetch + `pull --ff-only origin codex/rag-technical-discovery`: up-to-date; HEAD vẫn `6e0b3e9fcc835a7475dffa398b51b7583ec39520`.
- HEAD trước lúc bắt đầu có hai untracked user-data entries `docs/problem/` và `stitch-rag-consistency.zip`; giữ nguyên, không stage.
- Core-04 giữ Business Rules làm nguồn ưu tiên; không thêm `OWNER`, join code, self-join, endpoint cho resource service khác hoặc quyền ngoài rules.

### Git diff summary — R1 so với snapshot CORE-04 trước R1

Đối chiếu nội dung workspace với `CORE-04-review-bundle.zip` đã xuất trước R1: **9 file** thay đổi (7 tài liệu, 1 module Core, 1 test). Delta chỉ gồm `PRACTICE_ACCESS` Student-only cùng regression tests, contract/dependency-gate wording, và report này. `router.py`, schemas, caller allowlist, migration, SYS-02 và RAG/consumer code không đổi trong R1. Danh sách đầy đủ và unified diff nằm trong `CORE-04-R1-review-delta.zip`.

## 2. CORE-T03 endpoint và error contract

Endpoint đã đăng ký trong Core Internal router:

`POST /internal/v1/authorization/check`

Strict request: `{user_id: UUID, resource_type: "class", resource_id: UUID, action: AuthorizationAction}`. Response chỉ có `{allowed: boolean}`. Pydantic cấm field thừa; `resource_type` hiện chỉ `class`. ID tài liệu, assignment hoặc resource thuộc service khác không được chấp nhận/tra cứu.

Authentication: Bearer Service JWT do `lumi-service-auth` xác minh, `aud=core`, scope `core:check_access`. Trusted subject quyết định caller-action allowlist. Route không chấp nhận User JWT hoặc X-Service-Key.

| Trường hợp | HTTP/result |
|---|---|
| Request hợp lệ, policy cho phép | 200 `{"allowed":true}` |
| Business deny, user/class unknown hoặc cross-school | 200 `{"allowed":false}`; không tiết lộ class existence/status |
| Thiếu/sai/expired Service JWT hoặc User JWT | 401 |
| Thiếu scope hoặc caller/action mismatch | 403 |
| Field/UUID/action/resource type sai hoặc field thừa | 422 |
| SQLAlchemy/database outage | 503; không fallback sang allow |

Không trả user, school, membership, teaching role hoặc trạng thái lớp. Các lỗi dùng Core error envelope/correlation ID.

## 3. Caller/action matrix

| Service identity | Actions được gọi |
|---|---|
| `document` | DOCUMENT_READ, DOCUMENT_SHARE, DOCUMENT_MANAGE |
| `ai` | AI_QUERY |
| `learning` | PRACTICE_ACCESS, ASSIGNMENT_CREATE, ASSIGNMENT_SUBMIT, ASSESSMENT_MANAGE, GRADE_MANAGE, ANALYTICS_VIEW |
| Notification hoặc caller khác | Không có action |

Service có scope `core:check_access` nhưng action không nằm trong caller matrix bị 403 trước khi policy query chạy. Ma trận ở `services/core/app/modules/classroom/authorization.py:3–27`; endpoint kiểm tra ở `router.py:492–511`.

## 4. Mapping đủ 10 actions

| Target action | Allowed caller | Business Rule/FRS evidence | Existing policy | Core-side implementation | Resource-side responsibility |
|---|---|---|---|---|---|
| DOCUMENT_READ | document | BR-B7 `BUSINESS_RULES.md:28`; FRS-D04 `04_FRS_Document.md:37–44` | READ_DOCUMENT_SOURCE | Reuse current Student membership hoặc Lecturer assignment; same-school ACTIVE user. Lớp archived chỉ được coi là read gate. | Document kiểm owner/grant, version SUCCESS hiện hành, download/preview permission và revoke. |
| DOCUMENT_SHARE | document | BR-B2/B6 `BUSINESS_RULES.md:23,27`; FRS-D03 `04_FRS_Document.md:28–35` | Không có action tương đương | PRIMARY/ASSISTING assignment hiện hành và lớp ACTIVE; không map calendar/moderation. | Document kiểm source ownership/quyền share, grant state, revoke, idempotency và audit. |
| DOCUMENT_MANAGE | document | BR-B1/B2 `BUSINESS_RULES.md:22–23`; FRS-D01/D03 `04_FRS_Document.md:9–16,28–35` | Không có action tương đương | Với resource class, chỉ assigned Lecturer trong lớp ACTIVE. Không dùng class gate để suy ra owner source. | Document phải xác minh owner trước source edit/delete. Quản lý thư viện cá nhân ngoài class scope không gọi adapter này. |
| AI_QUERY | ai | BR-C1/C4/C5/H5 `BUSINESS_RULES.md:31,34–35,74`; Core FRS `03_FRS_Core.md:161–163` | USE_AI_TUTOR | Reuse: chỉ Student membership hiện hành trong lớp ACTIVE; Lecturer không được mở quyền. | AI/Document kiểm grant, version, retrieval scope, citation và revalidate trước response. |
| PRACTICE_ACCESS | learning | BR-D0/D3 `BUSINESS_RULES.md:39,42`; FRS Learning L02 `05_FRS_Learning.md:24–31`; CORE04-D02-A | PARTICIPATE_CURRENT_CLASS là quá rộng vì cho Lecturer; không reuse | Student-only custom gate: user ACTIVE/cùng trường, lớp ACTIVE, current Student membership. Multi-role user chỉ được allow nếu thật sự có eligibility Student hiện hành. | Learning kiểm attempt owner, practice resource, deadline, version và result ownership; Lecturer preview/management dùng permission khác trong Learning. |
| ASSIGNMENT_CREATE | learning | BR-D5/D7 `BUSINESS_RULES.md:43,46`; FRS-L01/L04 `05_FRS_Learning.md:15–21,42–48` | Không có action tương đương | PRIMARY/ASSISTING assignment hiện hành và lớp ACTIVE; không map `MANAGE_CLASS_CALENDAR`. | Learning kiểm draft/publish state, assignment policy, deadline và resource owner. PRIMARY approval áp dụng cho nội dung/công bố nhạy cảm. |
| ASSIGNMENT_SUBMIT | learning | FRS-L02/L04 `05_FRS_Learning.md:24–31,42–48`; BR-D5 `BUSINESS_RULES.md:43` | PARTICIPATE_CURRENT_CLASS quá rộng vì gồm Lecturer | Chỉ Student có membership hiện hành trong lớp ACTIVE. | Learning kiểm assignment version, due/open time, attempt count, idempotency và submission owner. |
| ASSESSMENT_MANAGE | learning | BR-D1/D4/D7 `BUSINESS_RULES.md:40,43,46`; FRS-L01/L03 `05_FRS_Learning.md:15–21,33–40` | Không có action tương đương; moderation không tương đương | PRIMARY/ASSISTING assignment hiện hành và lớp ACTIVE. | Learning cho ASSISTING draft/chấm theo phân công; chỉ PRIMARY phê duyệt công bố Assessment chính thức và các transition nhạy cảm. |
| GRADE_MANAGE | learning | BR-D4/D5 `BUSINESS_RULES.md:43–44`; FRS-L03 `05_FRS_Learning.md:33–40` | GRADE_SUBMITTED_WORK | Reuse: assigned Lecturer trong lớp ACTIVE. | Learning kiểm grader assignment, submission owner, grade lifecycle/history, audit và approval trước publish. |
| ANALYTICS_VIEW | learning | BR-E1/E2 `BUSINESS_RULES.md:50–51`; FRS-LI04 `06_FRS_Intelligence.md:32–38` | READ_OWN_HISTORY chỉ là Student history, không đại diện teacher/admin aggregate | Student có membership history; Lecturer có current assignment; Admin cùng trường. Vì đây là read-only analytics, gate không yêu cầu lớp ACTIVE. | Learning chỉ trả Student owner-only; Lecturer scope lớp được giao; Admin aggregate/report có suppression/audit. Không trả private chat/raw records ngoài policy. |

### Quy tắc disposition

- Tất cả 10 target action có enum, caller allowlist và class-side disposition. `ANALYTICS_VIEW` dùng BR-E1/E2 và FRS-LI04; Learning vẫn sở hữu data aggregation/suppression.
- CORE04-D01-A và D02-A được chấp thuận: Practice Student-only; approval actions là dependency gate nhưng deferred.
- Learning approval workflows phải chờ đến khi Core triển khai và xác minh riêng `ASSESSMENT_APPROVE` và `GRADE_CORRECTION_APPROVE`; ASSISTING không được phê duyệt thay PRIMARY.
- Existing action chỉ được reuse khi semantics khớp: DOCUMENT_READ, AI_QUERY và GRADE_MANAGE. PRACTICE_ACCESS không reuse PARTICIPATE_CURRENT_CLASS; ASSIGNMENT/ASSESSMENT và Document share/manage dùng predicates riêng, không mượn calendar/moderation.
- ASSESSMENT_APPROVE và GRADE_CORRECTION_APPROVE được CORE04-D01-A chấp thuận như dependency cho Learning; R1 không thêm chúng vào schema/action registry/caller allowlist. ASSESSMENT_MANAGE/GRADE_MANAGE không thay approval riêng của PRIMARY.
- Core chỉ quyết định quyền lớp hiện hành. Document/Learning/AI vẫn phải kiểm tra resource-local authorization; `allowed:true` không thay owner/grant/attempt/assignment checks.
- PRIMARY/ASSISTING đều là Lecturer assignment hiện hành; đặc quyền PRIMARY phê duyệt nằm ở Learning resource policy, không mở rộng trong Core.

Boundary/consumer evidence: `docs/architect/document-discovery/04_API_COMPATIBILITY.md:30–39,59–61`, `06_SECURITY_AND_RESILIENCE_REVIEW.md:19–22,56–70`, `docs/architect/learning-design/04_INTERNAL_API.md:2–5` và `06_SECURITY_RESILIENCE.md:2`. Các tài liệu yêu cầu Core class authorization tách khỏi Document owner/grant/version và Learning attempt/grade/D6 policy.

### CORE04-RV07–10 disposition

| Finding | R1 resolution | Status |
|---|---|---|
| RV07 — PRIMARY approval contract | Giữ `ASSESSMENT_MANAGE`/`GRADE_MANAGE` làm class-side management gates; ghi nhận `ASSESSMENT_APPROVE` và `GRADE_CORRECTION_APPROVE` là action Core riêng cần có trước Learning approval flows. Gate tương lai phải xác minh user ACTIVE, cùng school, lớp ACTIVE và PRIMARY teaching assignment hiện hành; ASSISTING không được allow, không dùng role claim cũ. Learning vẫn xác minh resource ownership, assignment, workflow state và approval eligibility. Không thêm hai action vào enum/caller matrix R1. | RESOLVED AT CONTRACT LEVEL; approval implementation DEFERRED. |
| RV08 — PRACTICE_ACCESS | Student-only theo user ACTIVE, same-school, ACTIVE class và current Student membership; multi-role users phải có eligibility Student thực tế. Không dùng legacy `PARTICIPATE_CURRENT_CLASS`; legacy semantics giữ nguyên. | RESOLVED. |
| RV09 — OpenAPI error contract | OpenAPI route contract kiểm tra 200 response, error envelope cho 401/403/422/500/503; dùng reusable `ERROR_RESPONSE`, không đổi global handler/public API. Identity snapshot ghi nhận shared `ServiceJWT` security scheme mà public ops vẫn giữ `HTTPBearer`. | RESOLVED. |
| RV10 — Server verification | Không truy cập server/SSH; ghi rõ PostgreSQL revoke/concurrency, full suite, Docker build và real consumer integration chưa xác minh. | DEFERRED / SERVER-01 BLOCKED. |

## 5. Code và contract changes

- `services/core/app/modules/classroom/schemas.py:30–44,266–273`: resource enum chỉ `class`, registry đủ 10 action, strict request/response.
- `services/core/app/modules/classroom/authorization.py:3–27`: service identity/action allowlist.
- `services/core/app/modules/classroom/public.py:42–141,224–273`: live context qua Core Identity/Classroom public/repository; giữ legacy policy, thêm 10 class-side rules.
- `services/core/app/modules/classroom/router.py:58–61,492–511`: Service JWT dependency, POST route, caller gate, DB fail-closed; legacy GET bắt đầu tại router.py:515.
- `services/core/tests/classroom/test_authorization.py:152–525`: class action matrix, service caller matrix, endpoint/auth/validation/outage/OpenAPI/legacy regression.
- Docs cập nhật: `core-design/04_INTERNAL_API.md`, Core `API_CONTRACT.md`, Core README, `FOLDER_STRUCTURE.md`, test README, CORE roadmap/MIP.
- Không sửa schema/migration, dependency SYS-02 hoặc RAG/Document/Learning consumer code; không query database service khác.

## 6. Test/verification evidence

| Command | Exit | Kết quả |
|---|---:|---|
| `rtk proxy .venv/Scripts/python.exe -m pytest tests/classroom/test_authorization.py tests/classroom/test_contract.py tests/security/test_service_jwt.py tests/test_common.py -q -p no:cacheprovider -W error` (workdir `services/core`) | 0 | 197 passed in 6.66s. |
| `rtk proxy .venv/Scripts/ruff.exe check --config pyproject.toml app/modules/classroom/authorization.py app/modules/classroom/public.py app/modules/classroom/router.py app/modules/classroom/schemas.py tests/classroom/test_authorization.py` | 0 | All checks passed. |
| `rtk proxy .venv/Scripts/ruff.exe format --check --config pyproject.toml app/modules/classroom/authorization.py app/modules/classroom/public.py app/modules/classroom/router.py app/modules/classroom/schemas.py tests/classroom/test_authorization.py` | 0 | Formatting passed. |
| `rtk proxy .venv/Scripts/python.exe -m pytest tests/identity/test_openapi.py -q -p no:cacheprovider -W error` | 0 | 2 passed in 1.72s; Identity bearer operations unchanged, global OpenAPI snapshot includes the new `ServiceJWT` scheme. |
| `rtk docker compose config --quiet` | 0 | Compose config hợp lệ. |

No full Core suite, PostgreSQL integration, Docker image build, server access, Production access or consumer integration ran in this task. SERVER-01 remains blocked.

## 7. CORE04-AC01–12

| AC | Status | Evidence/limitation |
|---|---|---|
| CORE04-AC01 — POST contract | LOCAL PASS | Strict UUID/class/action DTO, `{allowed}` response, endpoint OpenAPI test and Identity OpenAPI snapshot. |
| CORE04-AC02 — Service JWT only | LOCAL PASS | Real Service JWT passes; missing/invalid/User JWT/X-Service-Key reject; wrong audience rejected. |
| CORE04-AC03 — caller-specific actions | LOCAL PASS | `document`/`ai`/`learning` allowlist; Notification/unknown callers denied; caller-action mismatch 403. |
| CORE04-AC04 — 10 actions | LOCAL PASS | All action enums and positive/negative policy tests are present; table in section 4 gives each disposition. |
| CORE04-AC05 — current state/Business Rules | LOCAL PASS | ACTIVE user, current DB role/school/membership/assignment and class lifecycle, no stale JWT role authority. |
| CORE04-AC06 — privilege/cross-school safety | LOCAL PASS | Student submit-only, no Lecturer AI_QUERY, PRIMARY/ASSISTING assignment tests, cross-school/unknown class indistinguishable deny. |
| CORE04-AC07 — fail closed | LOCAL PASS | Invalid request 422, bad auth 401, caller/action 403, business deny false, DB failure 503. |
| CORE04-AC08 — legacy compatibility | LOCAL PASS | Existing GET/X-Service-Key method and response regression test; route unchanged. |
| CORE04-AC09 — service boundaries | LOCAL PASS | Only class UUID accepted; no foreign service DB access; local owner/grant/version/attempt policy remains service-owned. |
| CORE04-AC10 — docs/consumer guidance | LOCAL PASS | API contract, Core internal design/README and test guidance updated. No consumer migrated. |
| CORE04-AC11 — automated evidence | LOCAL PASS | 197 targeted Core/service tests, 2 OpenAPI tests, Ruff/format; no full suite claim. |
| CORE04-AC12 — Testing server/full PostgreSQL | BLOCKED — SERVER-01 | Endpoint/fingerprint not verified; SSH not retried; no server/Production access. |

### Existing Core AC impact

- C-AC12: service boundary/claims are locally verified through endpoint tests; real service rollout remains pending.
- C-AC13: action mapping and fail-closed Core gate locally verified; not a consumer integration test.
- C-AC08 remains PARTIAL until external Document/Learning/AI revoke behavior is integrated.
- C-AC20 NOT VERIFIED; no real cross-service consumer or event delivery was tested.
- C-AC01 public registration conflict remains open and outside CORE-04.

## 8. Blockers and stop condition

- SERVER-01 blocks full PostgreSQL/Core suite, Docker build and cross-service integration. Do not retry SSH until Testing endpoint/fingerprint are verified.
- Resource owner/grant/version, Learning attempt/assignment/grade transitions and AI retrieval revocation are resource-service responsibilities; no consumer has been migrated.
- The endpoint returns only a Core class-side decision; it must not be treated as complete authorization for a service-owned resource.
- Runtime key provisioning và quy trình rotation/reload vẫn pending; consumer rollout chưa diễn ra.
- CORE-00 discovery is CLOSED; no Business Rule changed. No migration was required.

No DOC-01/DOC-02, Document skeleton, RAG code, consumer migration, deployment, PR or merge is part of CORE-04.

**Final state:** CORE-04 — CLOSED & PUSHED, LOCAL ENGINEERING ACCEPTED, SERVER VERIFICATION BLOCKED.
