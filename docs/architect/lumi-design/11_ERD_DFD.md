# SƠ ĐỒ DỮ LIỆU — ERD, DFD, SEQUENCE VÀ STATE

**Mã:** LUMI-MODEL-001 · **Phiên bản:** 1.0-DRAFT · **Trạng thái:** Core ERD dựa trên ORM và SDD; future ERD chỉ là logical proposal.

## 1. ERD Core — mức logic kiểm chứng được

```mermaid
erDiagram
  SCHOOL ||--o{ USER : scopes
  SCHOOL ||--o{ ACADEMIC_YEAR : has
  SCHOOL ||--o{ COURSE : offers
  USER ||--o{ ROLE_ASSIGNMENT : assigned
  USER ||--o{ AUTH_SESSION : owns
  USER ||--o{ ONE_TIME_TOKEN : receives
  USER ||--o{ DATA_REQUEST : raises
  ACADEMIC_YEAR ||--o{ SEMESTER : has
  ACADEMIC_YEAR ||--o{ HOMEROOM_CLASS : contains
  HOMEROOM_CLASS ||--o{ HOMEROOM_ROSTER : has
  USER ||--o{ HOMEROOM_ROSTER : student
  COURSE ||--o{ SUBJECT_CLASS : defines
  SEMESTER ||--o{ SUBJECT_CLASS : schedules
  HOMEROOM_CLASS o|--o{ SUBJECT_CLASS : source
  SUBJECT_CLASS ||--o{ CLASS_MEMBERSHIP : enrolls
  USER ||--o{ CLASS_MEMBERSHIP : participates
  SUBJECT_CLASS ||--o{ TEACHING_ASSIGNMENT : staffed_by
  USER ||--o{ TEACHING_ASSIGNMENT : teaches
  SUBJECT_CLASS ||--o{ CLASS_POST : includes
  CLASS_POST ||--o{ POST_COMMENT : comments
  SUBJECT_CLASS ||--o{ CALENDAR_EVENT : schedules
  USER ||--o{ NOTIFICATION : recipient
```

> Đây là ERD **logical**: không hiển thị đầy đủ FK/index/constraint, nullable và cột audit. Tên bảng vật lý có thể khác nhãn diagram; ví dụ ORM dùng `homeroom_classes`, `homeroom_rosters`, `subject_classes`, `class_memberships`.

## 2. Candidate ERD Document — PROPOSED

```mermaid
erDiagram
  DOCUMENT ||--o{ DOCUMENT_VERSION : versions
  DOCUMENT ||--o{ CLASS_DOCUMENT_GRANT : shared_with
  DOCUMENT_VERSION ||--o{ PROCESSING_JOB : processed_by
  DOCUMENT ||--o{ SOURCE_NOTE : referenced_by
  DOCUMENT ||--o{ BOOKMARK : marked_by
  DOCUMENT {
    uuid id PK
    uuid owner_user_id
    string title
  }
  DOCUMENT_VERSION {
    uuid id PK
    uuid document_id FK
    int version_no
    string state
    string blob_ref
  }
  CLASS_DOCUMENT_GRANT {
    uuid id PK
    uuid document_id FK
    uuid class_id
    timestamp revoked_at
  }
```

Core class_id/user_id chỉ là external identifiers; **không có FK trực tiếp sang DB Core**.

## 3. Candidate ERD Learning — PROPOSED

```mermaid
erDiagram
  LEARNING_ACTIVITY ||--o{ ACTIVITY_VERSION : publishes
  ACTIVITY_VERSION ||--o{ QUESTION : contains
  ACTIVITY_VERSION ||--o{ ATTEMPT : attempted_as
  ATTEMPT ||--o{ SAVED_ANSWER : stores
  ATTEMPT ||--o| SUBMISSION : finalizes
  SUBMISSION ||--o{ GRADE_REVISION : graded_as
  GRADE_REVISION ||--o{ APPEAL : challenged_by
  LEARNING_ACTIVITY {
    uuid id PK
    uuid class_id
    string kind
  }
  ATTEMPT {
    uuid id PK
    uuid version_id FK
    uuid student_id
    string status
  }
  GRADE_REVISION {
    uuid id PK
    uuid submission_id FK
    int version
    string status
  }
```

Không lấy mô hình này làm migration khi chưa quyết định Practice/Assessment/Assignment có bảng riêng hay chung.

## 4. Candidate ERD Learner Intelligence — PROPOSED

```mermaid
erDiagram
  EVIDENCE_EVENT ||--o{ MASTERY_SNAPSHOT : contributes_to
  MASTERY_SNAPSHOT ||--o{ RECOMMENDATION : motivates
  REPORT_EXPORT {
    uuid id PK
    uuid actor_id
    string format
    string status
  }
  EVIDENCE_EVENT {
    uuid event_id PK
    uuid source_id
    int source_version
    uuid student_id
    string topic_id
  }
  MASTERY_SNAPSHOT {
    uuid id PK
    uuid student_id
    string topic_id
    string status
  }
```

Nguồn evidence là Learning qua contract, không join SQL trực tiếp.

## 5. DFD Level 0 — ranh giới Lumi

```mermaid
flowchart LR
  Admin[Admin] -->|Tài khoản/lớp/audit request| S((Lumi))
  Teacher[Lecturer] -->|Post/calendar/content/grades| S
  Student[Student] -->|Login/content/answers/data request| S
  S -->|Trạng thái/tài nguyên được phép| Admin
  S -->|Lớp/hoạt động/kết quả được phép| Teacher
  S -->|Lớp/notification/tiến độ| Student
  S -->|Email staff invitation/recovery| SMTP[SMTP Provider]
  S <-->|Core records| DB[(PostgreSQL Core)]
```

**Data trust:** Browser chỉ là requester, không quyết định School scope hoặc access control.

## 6. DFD Level 1 — Core đang triển khai

```mermaid
flowchart TB
  U[Browser/User] --> Id[1. Identity/Auth]
  U --> Adm[2. Administration]
  U --> Cl[3. Classroom]
  U --> Soc[4. Social/Calendar]
  U --> Not[5. Notifications]
  Id <--> DB1[(Core User/Session)]
  Adm <--> DB2[(Import/DataRequest/Audit)]
  Cl <--> DB3[(Class/Roster/Membership)]
  Soc <--> DB4[(Post/Comment/Event)]
  Cl --> Ob[(Outbox V2)]
  Soc --> Ob
  Ob --> Worker[Notification worker]
  Worker --> DB5[(Notification Inbox)]
  Not --> DB5
  Cl -. action-based check .-> Id
  Soc -. class/role checks .-> Cl
```

**Không mô tả thành 5 microservices Core**: 5 ô trên là module trong một FastAPI service, dùng chung transaction/schema theo boundary đã triển khai.

## 7. DFD Level 2 — Student import/roster

```mermaid
flowchart LR
  File[CSV/XLSX input] --> Parser[Validate + parse]
  Parser --> Preview[(Import batch preview)]
  Admin[Admin confirm] --> Confirm[Version/scope re-check]
  Preview --> Confirm
  Confirm --> Users[(Student / Identity)]
  Confirm --> Roster[(Homeroom roster)]
  Confirm --> Audit[(Audit)]
  Confirm --> Outbox[(Outbox)]
```

- Không lưu raw file/formula vào client-visible response nếu không cần.
- Transaction commit nhất quán; replay dùng kết quả import batch bền vững.

## 8. Sequence — revoke và historical access (future Document)

```mermaid
sequenceDiagram
 actor U as Học sinh
 participant W as Web
 participant D as Document
 participant C as Core access-check
 participant DB as Document grant
 U->>W: Mở tài liệu
 W->>D: GET source request
 D->>C: check action current
 C-->>D: allowed/denied
 D->>DB: check active grant
 DB-->>D: active/revoked
 alt both allowed
 D-->>W: content/secure link
 else denied/revoked/dependency failure
 D-->>W: Deny; do not reveal source
 end
```

## 9. Sequence — save/submit và grade event (future Learning)

```mermaid
sequenceDiagram
 actor Student
 participant Web
 participant L as Learning
 participant DB as Learning DB
 participant LI as Learner Intelligence
 Student->>Web: Lưu câu trả lời
 Web->>L: PATCH answer w/revision
 L->>DB: commit answer + increment revision
 L-->>Web: ACK revision
 Student->>Web: Nộp bài
 Web->>L: POST submit (idempotent)
 L->>DB: transaction finalization/grade draft
 L-->>Web: receipt (stable)
 Note over L,LI: Chỉ event grade đã có hiệu lực mới được dùng
 L-->>LI: versioned approved result event
 LI->>LI: dedup/version check
```

## 10. Danh sách sơ đồ cần cập nhật khi triển khai

| Sơ đồ | Hiện trạng | Điều kiện cập nhật |
|---|---|---|
| Core ERD physical | Logical snapshot này; migration là chuẩn | Sau mỗi migration/ORM change |
| Document logical/physical | PROPOSED | Sau ADR storage/schema/API |
| Learning attempt/grade | PROPOSED | Sau quyết định version/transfer/approval |
| Intelligence evidence | PROPOSED | Sau model/evaluation contract |
| AI | **OUT OF SCOPE** | Không vẽ trong giai đoạn này |