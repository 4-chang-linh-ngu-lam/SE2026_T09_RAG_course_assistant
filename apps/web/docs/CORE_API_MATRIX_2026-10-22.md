# Core HTTP implementation matrix - 2026-10-22

Document follow-up (23 October): [TASK-017 implementation and live verification](DOCUMENT_SERVICE_IMPLEMENTATION_2026-10-23.md). Document uses its own approved27-operation allowlist at `/api/document/v1`; Core's63 public operations remain unchanged. A scoped Core internal event intake connects Document changes to Notifications.

Class feed/notification follow-up: [23 October UI and synchronization](CORE_CLASS_FEED_NOTIFICATIONS_2026-10-23.md). Existing HTTP operations are unchanged; session-scoped foreground refresh, shared inbox state and ID-based notification targets are implemented without widening permissions.

Login/email follow-up: [role-specific activation and email links](CORE_EMAIL_LINK_FLOW_2026-10-23.md). The 63-operation wire surface is unchanged; email links now open the correct existing Staff/Reset page and only the Student tab exposes Student activation.

Current functional integration follow-up: [Web–Core connection fixes, 23 October](CORE_WEB_CONNECTION_FIXES_2026-10-23.md). Home/overview use the existing class reads; archived links, UUID identity and mutation reconciliation are repaired. Performance optimization is deferred under the user's current priority. The approved 63-operation wire contract is unchanged.

Latest implementation and evidence: [Core completion — 23 October](CORE_COMPLETION_2026-10-23.md), including ten account/classroom management routes, three Admin forms and all63 proxy operations. Historical baselines: [Admin forms](CORE_ADMIN_FORMS_INTEGRATION_2026-10-22.md), [38 approved operations](CORE_APPROVED_INTEGRATION_2026-10-22.md) and [Web–Core verification](FULL_VERIFICATION_2026-10-22.md). HTTP/React render evidence remains separate from browser interaction and external SMTP delivery.

Latest runtime checks and corrected load methodology: [23 October follow-up](CORE_RUNTIME_FOLLOWUP_2026-10-23.md). The 63/67-operation contract is unchanged. Earlier p95 measurements are historical, not a certification of the latest baseline.

Observed from the running Core OpenAPI at `http://localhost:8000/openapi.json` and the frontend operation allowlist. Branch: `frontend1`, HEAD `9e7669cbec9d21cd076f8b7b54411cec0ab1b7c8` plus existing uncommitted Core implementation and integration changes. The user's explicit approval is recorded below; runtime presence alone never approves a contract. No business payloads, credentials, cookies or tokens were exported.

Updated 2026-10-23: **67 HTTP operations**, **63 allowlisted frontend operations** (14 Identity + 3 Notifications + 23 Classroom + 8 Social + 4 Calendar + 11 Administration/import). After [Notifications](CORE_NOTIFICATION_CONTRACT_REVIEW_2026-10-22.md) and [38 existing operations](CORE_REMAINING_CONTRACT_REVIEW_2026-10-22.md), the user authorized completing Core including [eight proposed metadata reads](CORE_MISSING_READS_PROPOSAL_2026-10-22.md). Snapshot generated from current Core source in isolated Docker, not the older local runtime. Register stays blocked; health/internal stay outside the proxy. No other service contracts or new mutation APIs are included.

## Transport conventions

- Public prefix: `/api/v1`; frontend browser calls same-origin port 3000, server-only proxy forwards to Core port 8000. Health is direct; internal access checks are service-only.
- JSON unless 204 (no body). Bearer access token; refresh/logout use HttpOnly `refresh_token` cookie at `/api/v1/auth`, with Origin checks.
- Pagination: `limit` 1..100, default 20; `cursor` opaque canonical base64url UUID, 22 characters. Never parse cursor as a raw UUID. Most lists return `{items,next_cursor}`; membership/teaching-assignment responses are arrays.
- Core and local proxy errors: `{error:{code,message,correlation_id}}` plus `X-Correlation-ID`. `Retry-After` is preserved on throttling. The security follow-up is recorded in [CORE_SECURITY_FIXES_2026-10-22.md](CORE_SECURITY_FIXES_2026-10-22.md).
- `X-Admin-Reason` is required on selected Classroom mutations and Administration mutations. Classroom requirements are enforced manually and are missing from its OpenAPI parameters.
- Do not assume a generic idempotency contract across all routers. Identity/Classroom use optional process-local caching; Student create/issue-code/activate reject Idempotency-Key. Import confirm has its own durable preview replay.
- Web only forwards each operation's query whitelist and the required reason enum (ADMIN_INTERVENTION/POLICY_VIOLATION/USER_REQUEST). It strips generic Idempotency-Key and service credentials. The public snapshot is [core-approved-openapi.json](../tests/contracts/core-approved-openapi.json); the route/status test covers all 63 approved operations.

## Workspace readiness after approval

| Capability | Current state |
|---|---|
| Identity / Notifications | Existing live clients and inbox retained |
| Student/teacher class list | Live scoped GET, pagination; no guessed class code, teacher role, name or count |
| Class feed/comments | Live read/write with foreground refresh and preserved drafts; author-only post/comment edit, current assignment/membership guards; explicit unknown reconciliation |
| Class calendar / account calendar | Live scoped read/write; LEARNING read-only, actual timezone instants, title-only edits preserve multi-day spans; Admin metadata scope cannot enumerate Social calendars |
| Admin audit | Live read, full cursor traversal, actual actor IDs and safe reason labels |
| Classroom administration / accounts | Eight metadata reads implemented; wire-compatible controllers use current accounts, catalog, roster, assignments and real versions. Current acceptance results are recorded separately after execution |
| Staff invite / Admin personal-data review / import wizard | Three live views/route mounting verified by controller/HTTP and React rendering actual server receipts. Original file bytes, safe one-time disclosure and actual review status; executor/download/job history remain uncontracted |

"Allowlisted / typed Core port" in the inventory describes operation-level integration, not completion of every screen. See [the implementation report](CORE_APPROVED_INTEGRATION_2026-10-22.md) for tests and remaining boundaries.

## Endpoint inventory

### Health

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /health/live` | - | 200 LivenessResponse | - | Public | Direct Core |
| `GET /health/ready` | - | 200 ReadinessResponse | - | Public | Direct Core |

### Identity

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `POST /api/v1/auth/register` | RegisterRequest | 403 FORBIDDEN (deprecated) | - | Public | Intentionally blocked |
| `POST /api/v1/auth/verify-email` | VerifyEmailRequest | 200 VerifyEmailResponse | header: idempotency-key? | Public | Allowlisted, no Identity port method |
| `POST /api/v1/auth/login` | LoginRequest | 200 TokenResponse | header: idempotency-key? | Public | Allowlisted / Identity client |
| `POST /api/v1/auth/activate` | ActivateStudentRequest | 204 (empty) | - | Public | Allowlisted / Identity client |
| `POST /api/v1/admin/students` | AdminCreateStudentRequest | 201 StudentCodeResponse | - | Bearer (current scope/role) | Allowlisted / Identity client |
| `POST /api/v1/admin/students/{user_id}/activation-codes` | IssueStudentCodeRequest | 200 StudentCodeResponse | path: user_id* | Bearer (current scope/role) | Allowlisted / Identity client |
| `POST /api/v1/auth/refresh` | - | 200 TokenResponse | header: origin?; header: referer?; header: idempotency-key?; cookie: refresh_token? | Cookie + Origin | Allowlisted / Identity client |
| `POST /api/v1/auth/logout` | - | 204 (empty) | header: origin?; header: referer?; header: idempotency-key?; cookie: refresh_token? | Cookie + Origin | Allowlisted / Identity client |
| `POST /api/v1/auth/logout-all` | - | 204 (empty) | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / Identity client |
| `POST /api/v1/auth/password/forgot` | ForgotPasswordRequest | 200 ForgotPasswordResponse | header: idempotency-key? | Public | Allowlisted / Identity client |
| `POST /api/v1/auth/password/reset` | ResetPasswordRequest | 204 (empty) | header: idempotency-key? | Public | Allowlisted / Identity client |
| `GET /api/v1/users/me` | - | 200 UserProfile | - | Bearer (current scope/role) | Allowlisted / Identity client |
| `PATCH /api/v1/users/me` | UpdateProfileRequest | 200 UserProfile | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / Identity client |
| `GET /api/v1/users/me/data-requests` | - | 200 Page_DataRequestResponse_ | query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / Identity client |
| `POST /api/v1/users/me/data-requests` | CreateDataRequest | 201 DataRequestResponse | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / Identity client |

### Classroom

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/admin/courses` | - | 200 Page[CourseResponse] | cursor?, limit? | ACTIVE ADMIN same school | Live catalog/course selection |
| `GET /api/v1/admin/academic-years` | - | 200 Page[AcademicYearResponse] | cursor?, limit? | ACTIVE ADMIN same school | Actual year labels |
| `GET /api/v1/admin/academic-years/{year_id}/semesters` | - | 200 Page[SemesterResponse] | year_id UUID; cursor?, limit? | ACTIVE ADMIN same school/year | Actual semester labels |
| `GET /api/v1/admin/homeroom-classes` | - | 200 Page[HomeroomResponse] | cursor?, limit? | ACTIVE ADMIN same school | Homeroom selection |
| `GET /api/v1/admin/homeroom-classes/{homeroom_id}/roster` | - | 200 RosterResponse | homeroom_id UUID | ACTIVE ADMIN same school | Current students/roster_version |
| `GET /api/v1/admin/classes/{class_id}/teaching-assignments` | - | 200 TeachingAssignmentResponse[] | class_id UUID | ACTIVE ADMIN same school | Current PRIMARY/ASSISTING only |
| `POST /api/v1/admin/courses` | CourseCreateRequest | 201 CourseResponse | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/homeroom-classes` | HomeroomCreateRequest | 201 HomeroomResponse | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PUT /api/v1/admin/homeroom-classes/{homeroom_id}/roster` | RosterRequest | 200 RosterResponse | path: homeroom_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/homeroom-classes/{homeroom_id}/students/{student_id}/transfer` | HomeroomTransferRequest | 200 RosterResponse | path: homeroom_id*; path: student_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes` | ClassCreateRequest | 201 ClassResponse | header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/classes` | - | 200 Page_ClassResponse_ | query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/classes/{class_id}` | - | 200 ClassResponse | path: class_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/classes/{class_id}/members` | - | 200 (MembershipResponse)[] | path: class_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PUT /api/v1/admin/classes/{class_id}/teaching-assignments` | TeachingAssignmentsRequest | 200 (TeachingAssignmentResponse)[] | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/enrollment/preview` | - | 200 EnrollmentPreviewResponse | path: class_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/admin/classes/{class_id}/enrollment-mode` | EnrollmentModeRequest | 200 ClassResponse | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/enrollment/sync` | - | 200 ClassResponse | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/members` | MembershipRequest | 201 MembershipResponse | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `DELETE /api/v1/admin/classes/{class_id}/members/{student_id}` | - | 204 (empty) | path: class_id*; path: student_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/members/{student_id}/transfer` | TransferRequest | 200 MembershipResponse | path: class_id*; path: student_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/archive` | - | 200 ClassResponse | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/classes/{class_id}/restore` | - | 200 ClassResponse | path: class_id*; header: idempotency-key? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |

### Internal

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /internal/v1/classes/{class_id}/access` | - | 200 InternalAccessResponse | path: class_id*; query: user_id*; query: action*; header: X-Service-Key? | X-Service-Key | Service-only |

### Social Feed

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/classes/{class_id}/posts` | - | 200 PostListResponse | path: class_id*; query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/classes/{class_id}/posts` | PostCreateRequest | 201 PostResponse | path: class_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/classes/{class_id}/posts/{post_id}` | PostUpdateRequest | 200 PostResponse | path: class_id*; path: post_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `DELETE /api/v1/classes/{class_id}/posts/{post_id}` | - | 204 (empty) | path: class_id*; path: post_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |

### Social Comments

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/classes/{class_id}/posts/{post_id}/comments` | - | 200 CommentListResponse | path: class_id*; path: post_id*; query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/classes/{class_id}/posts/{post_id}/comments` | CommentCreateRequest | 201 CommentResponse | path: class_id*; path: post_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/classes/{class_id}/posts/{post_id}/comments/{comment_id}` | CommentUpdateRequest | 200 CommentResponse | path: class_id*; path: post_id*; path: comment_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `DELETE /api/v1/classes/{class_id}/posts/{post_id}/comments/{comment_id}` | - | 204 (empty) | path: class_id*; path: post_id*; path: comment_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |

### Social Calendar

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/classes/{class_id}/calendar` | - | 200 CalendarEventListResponse | path: class_id*; query: from?; query: to?; query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/classes/{class_id}/calendar` | CalendarEventCreateRequest | 201 CalendarEventResponse | path: class_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/classes/{class_id}/calendar/{event_id}` | CalendarEventUpdateRequest | 200 CalendarEventResponse | path: class_id*; path: event_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `DELETE /api/v1/classes/{class_id}/calendar/{event_id}` | - | 204 (empty) | path: class_id*; path: event_id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |

### Notifications

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/notifications` | - | 200 NotificationListResponse | query: limit?; query: cursor? | Bearer (current recipient) | Allowlisted / live inbox, cursor traversal and global unread_count |
| `PATCH /api/v1/notifications/{id}/read` | - | 200 MarkReadResponse | path: id* | Bearer (current recipient) | Allowlisted / ACK validation and unknown reconciliation |
| `POST /api/v1/notifications/read-all` | - | 204 (empty) | - | Bearer (current recipient) | Allowlisted / GET reconciliation after unknown |

### Administration

| Method / path | Request JSON | Success JSON/status | Other input | Auth | Frontend exposure |
|---|---|---|---|---|---|
| `GET /api/v1/admin/users` | - | 200 Page[AdminUserReadDTO] | cursor?, limit? | ACTIVE ADMIN same school | Account list/student/teacher selection |
| `GET /api/v1/admin/users/{id}` | - | 200 AdminUserReadDTO | id UUID | ACTIVE ADMIN same school | Current role/status reconciliation |
| `POST /api/v1/admin/users` | AdminCreateUserRequest | 201 UserSummaryDTO | header: X-Admin-Reason* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/admin/users/{id}/status` | AdminUserStatusRequest | 204 (empty) | path: id*; header: X-Admin-Reason* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PUT /api/v1/admin/users/{id}/roles` | RoleUpdateCommand | 200 UserSummaryDTO | path: id*; header: X-Admin-Reason* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/admin/audit-events` | - | 200 Page_AuditEventResponse_ | query: actor_id?; query: action?; query: since?; query: until?; query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/admin/data-requests` | - | 200 Page_DataRequestResponse_ | query: limit?; query: cursor? | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `GET /api/v1/admin/data-requests/{id}` | - | 200 DataRequestResponse | path: id* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `PATCH /api/v1/admin/data-requests/{id}` | DataResolutionCommand | 200 DataRequestResponse | path: id*; header: X-Admin-Reason* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/students/imports/preview` | ImportPreviewRequest | 200 ImportPreviewResponse | - | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |
| `POST /api/v1/admin/students/imports/confirm` | ImportConfirmRequest | 200 ImportConfirmResponse | header: X-Admin-Reason* | Bearer (current scope/role) | Allowlisted / typed Core port; see workspace readiness |

## Schema fields

New read DTOs: AcademicYearResponse `{id:UUID,school_id:UUID,label:string}`; SemesterResponse `{id:UUID,academic_year_id:UUID,name:string}`; AdminUserReadDTO `{id:UUID,email:string|null,username:string|null,school_id:UUID|null,display_name:string|null,status:UserStatus,roles:Role[]}`. Roles may be empty for legacy records; never inferred. The account projection excludes passwords, hashes, one-time codes and session_version. Other read DTOs reuse the existing schemas below. New reads never require Admin reason or mutate audit/outbox. Malformed cursor400; scoped Classroom cursor400, scoped account cursor404; outside-school resources404. Full semantics: [Core API contract](../../../docs/architect/microservices-v1/core/API_CONTRACT.md).

`Required` means the key is required by the schema. A nullable required field must still be present with null. Runtime response serialization currently includes model defaults. Request models generally reject extra properties. JSON Schema does not capture every service/field validator (username normalization, timezone rules, duplicate IDs, school scope, status transitions).

### `ActivateStudentRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `username` | string | yes | maxLength=200; minLength=1 |
| `activation_code` | string (password) | yes | maxLength=256; minLength=1 |
| `new_password` | string (password) | yes | maxLength=128; minLength=12 |

Extra request fields: rejected.

### `AdminCreateStudentRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `username` | string | yes | maxLength=200; minLength=1 |
| `display_name` | string \| null | no | - |

Extra request fields: rejected.

### `AdminCreateUserRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `email` | string (email) | yes | maxLength=320 |
| `roles` | ("ADMIN" \| "LECTURER")[] | yes | maxItems=2; minItems=1 |

Extra request fields: rejected.

### `AdminUserStatusRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `status` | "ACTIVE" \| "LOCKED" | yes | - |

Extra request fields: rejected.

### `AuditEventResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `actor_id` | string (uuid) \| null | yes | - |
| `action` | string | yes | - |
| `target_type` | string | yes | - |
| `target_id` | string (uuid) | yes | - |
| `correlation_id` | string (uuid) | yes | - |
| `metadata_json` | object | yes | - |
| `occurred_at` | string (date-time) | yes | - |

### `AuthorSummary`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `display_name` | string \| null | no | - |

### `CalendarEventCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `title` | string | yes | maxLength=200; minLength=1 |
| `description` | string \| null | no | - |
| `starts_at` | string (date-time) | yes | - |
| `ends_at` | string (date-time) | yes | - |

Extra request fields: rejected.

### `CalendarEventListResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (CalendarEventResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `CalendarEventResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `class_id` | string (uuid) | yes | - |
| `title` | string | yes | - |
| `description` | string \| null | yes | - |
| `starts_at` | string (date-time) | yes | - |
| `ends_at` | string (date-time) | yes | - |
| `origin` | CalendarOrigin | yes | - |
| `external_ref` | string \| null | yes | - |

### `CalendarEventUpdateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `title` | string \| null | no | - |
| `description` | string \| null | no | - |
| `starts_at` | string (date-time) \| null | no | - |
| `ends_at` | string (date-time) \| null | no | - |

Extra request fields: rejected.

### `CalendarOrigin`

Type: `"CORE" | "LEARNING"`.

### `ClassAccessAction`

Type: `"read_class_content" | "participate_current_class" | "moderate_class_content" | "manage_class_calendar" | "read_own_history" | "read_document_source" | "use_ai_tutor" | "grade_submitted_work"`.

### `ClassCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `course_id` | string (uuid) | yes | - |
| `name` | string | yes | maxLength=200; minLength=1 |
| `academic_year` | string | yes | maxLength=30; minLength=1 |
| `semester` | string | yes | maxLength=50; minLength=1 |
| `grade_level` | integer | yes | maximum=12; minimum=6 |
| `homeroom_class_id` | string (uuid) \| null | no | - |
| `enrollment_mode` | EnrollmentMode | yes | - |
| `primary_lecturer_id` | string (uuid) | yes | - |

Extra request fields: rejected.

### `ClassResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `school_id` | string (uuid) | yes | - |
| `academic_year_id` | string (uuid) | yes | - |
| `semester_id` | string (uuid) | yes | - |
| `course_id` | string (uuid) | yes | - |
| `homeroom_class_id` | string (uuid) \| null | yes | - |
| `name` | string | yes | - |
| `grade_level` | integer | yes | - |
| `enrollment_mode` | EnrollmentMode | yes | - |
| `status` | ClassStatus | yes | - |
| `version` | integer | yes | - |

### `ClassStatus`

Type: `"ACTIVE" | "ARCHIVED"`.

### `CommentCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `body` | string | yes | maxLength=10000; minLength=1 |

Extra request fields: rejected.

### `CommentListResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (CommentResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `CommentResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `post_id` | string (uuid) | yes | - |
| `author` | AuthorSummary | yes | - |
| `body` | string | yes | - |
| `created_at` | string (date-time) | yes | - |
| `updated_at` | string (date-time) | yes | - |

### `CommentUpdateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `body` | string | yes | maxLength=10000; minLength=1 |

Extra request fields: rejected.

### `CourseCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `code` | string | yes | maxLength=50; minLength=1 |
| `name` | string | yes | maxLength=200; minLength=1 |

Extra request fields: rejected.

### `CourseResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `code` | string | yes | - |
| `name` | string | yes | - |
| `school_id` | string (uuid) | yes | - |

### `CreateDataRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `type` | DataRequestType | yes | - |
| `reason` | string \| null | no | - |

Extra request fields: rejected.

### `DataRequestResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `user_id` | string (uuid) | yes | - |
| `type` | DataRequestType | yes | - |
| `reason` | string \| null | yes | - |
| `status` | DataRequestStatus | yes | - |
| `resolution_note` | string \| null | yes | - |
| `created_at` | string (date-time) | yes | - |
| `updated_at` | string (date-time) | yes | - |

### `DataRequestStatus`

Type: `"PENDING" | "IN_REVIEW" | "COMPLETED" | "REJECTED"`.

### `DataRequestType`

Type: `"ACCESS" | "EXPORT" | "CORRECTION" | "DELETE"`.

### `DataResolutionCommand`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `status` | "IN_REVIEW" \| "COMPLETED" \| "REJECTED" | yes | - |
| `resolution_note` | "VERIFICATION_IN_PROGRESS" \| "POLICY_PENDING" \| "OUTSIDE_CORE_SCOPE" \| "INSUFFICIENT_VERIFICATION" \| "REQUEST_REJECTED" \| "DUPLICATE_REQUEST" | yes | - |
| `identity_verified` | boolean | no | default=false |

Extra request fields: rejected.

### `EnrollmentMode`

Type: `"AUTO" | "MANUAL"`.

### `EnrollmentModeRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `mode` | EnrollmentMode | yes | - |
| `expected_class_version` | integer \| null | no | - |
| `expected_roster_version` | integer \| null | no | - |

Extra request fields: rejected.

### `EnrollmentPreviewResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `class_id` | string (uuid) | yes | - |
| `target_mode` | EnrollmentMode | yes | - |
| `class_version` | integer | yes | - |
| `roster_version` | integer | yes | - |
| `add_student_ids` | (string (uuid))[] | yes | - |
| `end_student_ids` | (string (uuid))[] | yes | - |

### `ErrorDetail`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `code` | string | yes | - |
| `message` | string | yes | - |
| `correlation_id` | string (uuid) | yes | - |

### `ErrorEnvelope`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `error` | ErrorDetail | yes | - |

### `ForgotPasswordRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `email` | string (email) | yes | - |

Extra request fields: rejected.

### `ForgotPasswordResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `message` | string | no | default="If the account is eligible, password reset instructions will be sent." |

### `HomeroomCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `name` | string | yes | maxLength=200; minLength=1 |
| `academic_year` | string | yes | maxLength=30; minLength=1 |
| `grade_level` | integer | yes | maximum=12; minimum=6 |

Extra request fields: rejected.

### `HomeroomResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `school_id` | string (uuid) | yes | - |
| `academic_year_id` | string (uuid) | yes | - |
| `name` | string | yes | - |
| `grade_level` | integer | yes | - |
| `roster_version` | integer | yes | - |

### `HomeroomTransferRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `destination_homeroom_id` | string (uuid) | yes | - |

Extra request fields: rejected.

### `ImportConfirmRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `preview_id` | string (uuid) | yes | - |

Extra request fields: rejected.

### `ImportConfirmResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `preview_id` | string (uuid) | yes | - |
| `status` | "COMPLETED" | no | default="COMPLETED" |
| `replayed` | boolean | yes | - |
| `items` | (ImportResultItem)[] | yes | - |

### `ImportErrorResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `row` | integer | yes | - |
| `code` | string | yes | - |

### `ImportPreviewItem`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `row` | integer | yes | - |
| `action` | "CREATE" \| "EXISTING" \| "ASSIGN_USERNAME" | yes | - |
| `username` | string | yes | - |
| `user_id` | string (uuid) \| null | yes | - |

### `ImportPreviewRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `format` | "CSV" \| "XLSX" | yes | - |
| `content_base64` | string | yes | maxLength=2800000; minLength=1 |
| `homeroom_class_id` | string (uuid) \| null | no | - |

Extra request fields: rejected.

### `ImportPreviewResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `valid` | boolean | yes | - |
| `preview_id` | string (uuid) \| null | no | - |
| `expires_at` | string (date-time) \| null | no | - |
| `items` | (ImportPreviewItem)[] | no | default=[] |
| `errors` | (ImportErrorResponse)[] | no | default=[] |

### `ImportResultItem`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `row` | integer | yes | - |
| `outcome` | "CREATED" \| "EXISTING" \| "USERNAME_ASSIGNED" | yes | - |
| `student` | UserSummaryDTO | yes | - |
| `code` | string \| null | no | - |
| `expires_at` | string (date-time) \| null | no | - |

### `InternalAccessResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `allowed` | boolean | yes | - |
| `class_id` | string (uuid) | yes | - |
| `school_id` | string (uuid) \| null | no | - |
| `class_status` | ClassStatus \| null | no | - |
| `teaching_role` | TeachingRole \| null | no | - |
| `user_id` | string (uuid) | yes | - |
| `action` | ClassAccessAction | yes | - |

### `IssueStudentCodeRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `identity_verified` | boolean | no | default=false |

Extra request fields: rejected.

### `LivenessResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `status` | "live" | no | default="live" |

### `LoginRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `email` | string (email) \| null | no | - |
| `username` | string \| null | no | - |
| `password` | string (password) | yes | maxLength=128; minLength=1 |

Extra request fields: rejected.

### `MarkReadResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `read` | boolean | yes | - |

### `MembershipRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `student_id` | string (uuid) | yes | - |

Extra request fields: rejected.

### `MembershipResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `class_id` | string (uuid) | yes | - |
| `student_id` | string (uuid) | yes | - |
| `source` | EnrollmentMode | yes | - |
| `status` | MembershipStatus | yes | - |
| `joined_at` | string (date-time) | yes | - |
| `ended_at` | string (date-time) \| null | no | - |

### `MembershipStatus`

Type: `"ACTIVE" | "ENDED"`.

### `NotificationListResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (NotificationResponse)[] | yes | - |
| `unread_count` | integer | yes | - |
| `next_cursor` | string \| null | no | - |

### `NotificationResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `type` | string | yes | - |
| `payload_json` | object | yes | - |
| `read` | boolean | yes | - |
| `created_at` | string (date-time) | yes | - |

### `Page_AuditEventResponse_`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (AuditEventResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `Page_ClassResponse_`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (ClassResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `Page_DataRequestResponse_`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (DataRequestResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `PostCreateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `body` | string | yes | maxLength=10000; minLength=1 |

Extra request fields: rejected.

### `PostListResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `items` | (PostResponse)[] | yes | - |
| `next_cursor` | string \| null | no | - |

### `PostResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `class_id` | string (uuid) | yes | - |
| `author` | AuthorSummary | yes | - |
| `body` | string | yes | - |
| `created_at` | string (date-time) | yes | - |
| `updated_at` | string (date-time) | yes | - |

### `PostUpdateRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `body` | string | yes | maxLength=10000; minLength=1 |

Extra request fields: rejected.

### `ReadinessResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `status` | "ready" | no | default="ready" |
| `db` | "connected" | no | default="connected" |

### `RegisterRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `email` | string (email) | yes | - |
| `password` | string (password) | yes | maxLength=128; minLength=12 |

Extra request fields: rejected.

### `ResetPasswordRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `token` | string (password) | yes | maxLength=256; minLength=1 |
| `new_password` | string (password) | yes | maxLength=128; minLength=12 |

Extra request fields: rejected.

### `Role`

Type: `"STUDENT" | "LECTURER" | "ADMIN"`.

### `RoleUpdateCommand`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `roles` | ("ADMIN" \| "LECTURER" \| "STUDENT")[] | yes | maxItems=3; minItems=1 |

Extra request fields: rejected.

### `RosterRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `student_ids` | (string (uuid))[] | yes | - |

Extra request fields: rejected.

### `RosterResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `homeroom_class_id` | string (uuid) | yes | - |
| `student_ids` | (string (uuid))[] | yes | - |
| `roster_version` | integer | yes | - |

### `StudentCodeResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `student` | UserSummaryDTO | yes | - |
| `purpose` | "ACTIVATION" \| "PASSWORD_RESET" | yes | - |
| `code` | string | yes | - |
| `expires_at` | string (date-time) | yes | - |

### `TeachingAssignmentResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `class_id` | string (uuid) | yes | - |
| `lecturer_id` | string (uuid) | yes | - |
| `role` | TeachingRole | yes | - |
| `assigned_at` | string (date-time) | yes | - |
| `ended_at` | string (date-time) \| null | no | - |

### `TeachingAssignmentsRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `primary_lecturer_id` | string (uuid) | yes | - |
| `assisting_lecturer_ids` | (string (uuid))[] | no | - |

Extra request fields: rejected.

### `TeachingRole`

Type: `"PRIMARY" | "ASSISTING"`.

### `TokenResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `access_token` | string | yes | - |
| `token_type` | "bearer" | no | default="bearer" |
| `expires_in` | integer | no | default=900 |

### `TransferRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `destination_class_id` | string (uuid) | yes | - |

Extra request fields: rejected.

### `UpdateProfileRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `display_name` | string \| null | no | - |

Extra request fields: rejected.

### `UserProfile`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `email` | string (email) \| null | yes | - |
| `username` | string \| null | no | - |
| `school_id` | string (uuid) \| null | no | - |
| `display_name` | string \| null | yes | - |
| `roles` | (Role)[] | yes | - |
| `status` | UserStatus | yes | - |

### `UserStatus`

Type: `"PENDING_VERIFICATION" | "ACTIVE" | "LOCKED"`.

### `UserSummaryDTO`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `id` | string (uuid) | yes | - |
| `email` | string (email) \| null | yes | - |
| `username` | string \| null | no | - |
| `school_id` | string (uuid) \| null | no | - |
| `display_name` | string \| null | no | - |
| `status` | "PENDING_VERIFICATION" \| "ACTIVE" \| "LOCKED" | yes | - |

### `VerifyEmailRequest`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `token` | string (password) | yes | maxLength=256; minLength=1 |

Extra request fields: rejected.

### `VerifyEmailResponse`

| Field | Type | Required | Constraints / default |
|---|---|---|---|
| `verified` | true | no | default=true |
