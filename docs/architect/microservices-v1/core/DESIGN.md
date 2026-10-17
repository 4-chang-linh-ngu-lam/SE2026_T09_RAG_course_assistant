# Core Service — Thiết kế v1

**Trạng thái:** BASELINE THIẾT KẾ · **Ngày:** 2026-10-11. Identity đã triển khai tại TASK-001–004; Classroom Admin/access API và schema đã triển khai tại TASK-005–008, nhưng toàn Core G1/G2 vẫn chưa hoàn thành.

## 1. Công nghệ và xác thực (Identity legacy và mục tiêu được phân biệt)
- Một Core FastAPI service, Next.js Web, PostgreSQL schema `core`, SQLAlchemy, Alembic, Docker Compose.
- **IMPLEMENTED Identity:** Student do Admin cấp username + mã kích hoạt một lần, mặc định 24 giờ và cấu hình được; không cần email/SMTP, đặt mật khẩu khi kích hoạt, khôi phục qua Admin xác minh. Lecturer/Admin tiếp tục email/password; Student không login/reset bằng email. Public self-registration bị chặn 403. Không tự nâng quyền.
- JWT access **15 phút**, refresh **7 ngày**; refresh rotation, server lưu hash/phiên/revocation. Refresh cookie `HttpOnly; Secure; SameSite=Lax` trong mô hình cùng-site, access token giữ trong bộ nhớ client, không dùng localStorage. Hash password Argon2id.
- Khóa tài khoản, đổi mật khẩu, logout-all thu hồi phiên; backend kiểm tra trạng thái hiện hành. CSRF/Origin protection cho cookie mutations; rate limit login/activation/reset. Email verification/reset token một lần, hết hạn, lưu hash.
- Service-to-service access-check dùng service credential/scope riêng, không tin user_id từ browser.
- Access JWT có `sub` UUID, `roles`, `session_version`, `iat`, `exp`. Backend dùng role/status/session version hiện hành từ Identity public interface; role trong JWT không tự cấp quyền. Bootstrap đã nối Common lookup với Identity DB ở TASK-002; ứng dụng chưa nối vẫn từ chối an toàn.
- Token xác minh/reset lưu SHA-256, mặc định hết hạn sau 24 giờ/60 phút và cấu hình được. Refresh rotation giữ hạn gốc 7 ngày; dùng lại token revoked thu hồi family, không kéo dài hạn phiên. Logout thu hồi refresh hiện tại; logout-all/đổi mật khẩu/khóa tài khoản tăng session version và thu hồi toàn bộ refresh session.

## 2. Module và ownership
| Module | Trách nhiệm |
|---|---|
| identity | User, RoleAssignment, AuthSession, one-time token, DataRequest |
| classroom | School, AcademicYear, Semester, HomeroomClass, HomeroomRoster, Course, SubjectClass, TeachingAssignment, Membership, enrollment AUTO/MANUAL |
| social/feed | ClassPost |
| social/comments | PostComment |
| social/calendar | CalendarEvent và bản chiếu deadline Learning |
| notification | Notification, trạng thái đã đọc, dedup |
| administration | Admin workflows, Core audit |
| common | DB, config, security, errors, shared dependencies |

Các module giao tiếp qua `public.py`; không import repository module khác. [Folder Structure](FOLDER_STRUCTURE.md).

Public Identity trả DTO an toàn, batch summary một query; Admin helpers kiểm tra actor/role/status hiện hành, ghi audit cùng transaction và hỗ trợ session caller sở hữu. Chữ ký/cách dùng tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004).

## 3. Schema logic (UUID PK, UTC timestamptz)

**Bảng bên dưới là thiết kế lịch sử/chưa chắc đã triển khai, không phải schema MVP đã chốt.** Các bảng join_requests, co_lecturer_invitations, join_code_hash, owner_user_id là **LEGACY/OUT OF MVP**; không tạo mới theo mô hình này. Entity mục tiêu và migration được mô tả sau bảng.
| Bảng | Trường chính | Constraint |
|---|---|---|
| users | id,email?,username?,school_id?,activated_at?,display_name,password_hash,status,email_verified_at,session_version | email/username lowercase unique; status PENDING_VERIFICATION/ACTIVE/LOCKED; session_version mặc định 1 |
| role_assignments | user_id,role | unique(user_id,role); STUDENT/LECTURER/ADMIN |
| auth_sessions | id,user_id,refresh_hash,family_id,expires_at,revoked_at | refresh_hash unique; rotation atomically |
| one_time_tokens | id,user_id,purpose,token_hash,expires_at,consumed_at | token_hash unique; EMAIL_VERIFICATION/PASSWORD_RESET/ADMIN_INVITATION cho staff, STUDENT_ACTIVATION/STUDENT_PASSWORD_RESET cho Student |
| data_requests | id,user_id,request_type,reason,status,resolution_note,created_at,updated_at | ACCESS/EXPORT/CORRECTION/DELETE; PENDING/IN_REVIEW/COMPLETED/REJECTED; FK user không cascade; index(user_id,id) |
| courses | id,code,name | code unique |
| classes | id,course_id,owner_user_id,name,join_code_hash,join_enabled,status | status ACTIVE/ARCHIVED; join_code_hash unique |
| class_memberships | id,class_id,user_id,class_role,status,joined_at,ended_at | role OWNER/CO_LECTURER/STUDENT; status ACTIVE/LEFT/REMOVED; partial unique ACTIVE(class_id,user_id) |
| join_requests | id,class_id,student_id,status,decided_by,decided_at | PENDING/APPROVED/REJECTED/CANCELLED; partial unique PENDING(class_id,student_id) |
| co_lecturer_invitations | id,class_id,lecturer_id,status,expires_at | PENDING/ACCEPTED/REJECTED/CANCELLED |
| class_posts | id,class_id,author_id,body,deleted_at | soft delete |
| post_comments | id,post_id,author_id,body,deleted_at | soft delete |
| calendar_events | id,class_id,title,starts_at,ends_at,origin,external_ref,version | CORE/LEARNING; unique(origin,external_ref) nếu có |
| notifications | id,recipient_id,type,payload_json,dedup_key,read_at | dedup_key unique |
| audit_events | id,actor_id,action,target_type,target_id,correlation_id,metadata_json,occurred_at | tối thiểu, không lưu chat/token |
| outbox_events | id,event_type,aggregate_id,payload_json,created_at,published_at | phát event sau commit |

FK chỉ trong Core; index theo class_id/user_id/created_at. Alembic migration là hiện thực schema, không phải bảng đã tồn tại.

## 4. State machine (DECIDED nghiệp vụ, PENDING DESIGN kỹ thuật)
- Student: Admin tạo PENDING_VERIFICATION (enum legacy dùng chung cho trạng thái chờ kích hoạt; email không bắt buộc) → ACTIVE với activated_at → LOCKED/ACTIVE do Admin. Mã STUDENT_ACTIVATION một lần, mặc định 24 giờ (`STUDENT_ACTIVATION_EXPIRE_HOURS`). Không tự mở LOCKED qua activate/reset. Chi tiết được người dùng duyệt 2026-10-14.
- SubjectClass: ACTIVE ↔ ARCHIVED, chỉ Admin chuyển; archived chỉ đọc hoạt động chung, học sinh vẫn đọc/sửa notes cá nhân hợp lệ.
- Enrollment: AUTO đồng bộ từ homeroom roster, MANUAL do Admin cập nhật; đổi MANUAL→AUTO phải preview/confirm; mọi thay đổi idempotent, audit, không xóa lịch sử.
- Membership: ACTIVE → ENDED khi chuyển lớp/kết thúc; tái ghi danh phải giữ lịch sử từng đợt, một ACTIVE/class/student; thời điểm hiệu lực **PENDING DESIGN**.
- Transfer: chấm dứt tham gia lớp cũ; submitted-ungraded tiếp tục chấm, unsubmitted đóng, timed attempt xử lý theo assessment policy, không mặc định hoàn thành.
- TeacherAssignment: PRIMARY/ASSISTING do Admin quản lý, không có teacher-to-teacher invitation hay ownership transfer.
- Các state machine JoinRequest/approve và owner transfer cũ **OUT OF MVP**.

## 5. Quyền (DECIDED)
| Hành động | Admin | Giáo viên chính | Giáo viên phối hợp | Student |
|---|---|---|---|---|
| Tạo lớp, roster, ghi danh, chuyển lớp, phân công giáo viên | Có + audit | Không | Không | Không |
| Archive/restore | Có + audit | Không | Không | Không |
| Quản lý tài liệu/hoạt động lớp được phân công | Can thiệp theo thẩm quyền | Có | Có, theo grant | Không |
| Tạo nháp Assessment / bài luyện tập / bài tập | Theo quy trình | Có | Có | Không |
| Công bố Assessment chính thức | Can thiệp ngoại lệ có lý do | Phê duyệt | Đề xuất | Không |
| Chấm bài được phân công | Theo quy trình | Có | Có | Không |
| Sửa điểm đã công bố / hủy kết quả | Can thiệp ngoại lệ có lý do | Phê duyệt + audit | Đề xuất | Không |
| Xem lịch sử cá nhân | Theo chính sách, không mặc định | Theo lớp được giao | Theo lớp được giao | Chỉ dữ liệu của mình |
| Đọc chat AI riêng tư | Không mặc định | Chỉ khi học sinh chia sẻ cụ thể | Chỉ khi học sinh chia sẻ cụ thể | Chủ chat |

Quyền kiểm tra theo hành động + trạng thái + phạm vi trường/lớp + grant; không đồng nhất `read_own_history` với `membership ACTIVE`. Từ chối an toàn khi không xác minh được quyền.

## 6. Luồng (DECIDED, API chi tiết PROPOSED)
1. Admin tạo Student/nhập CSV/Excel → kiểm tra trùng/lỗi → cấp username + mã kích hoạt → Student kích hoạt và đặt mật khẩu; không dùng public Student register.
2. Admin tạo lớp hành chính, roster, lớp môn học và phân công PRIMARY/ASSISTING → AUTO sync hoặc MANUAL roster → audit/outbox. Không dùng join code.
3. Student chuyển lớp → kết thúc participation lớp cũ, giữ dữ liệu lịch sử cá nhân → Learning xử lý submissions/attempts theo chính sách.
4. Feed/comments/calendar: kiểm tra membership hoặc teaching assignment hiện hành theo action, trường/lớp và trạng thái tài khoản; soft delete/audit, archived chặn ghi hoạt động chung. Deadline Learning là nguồn chính thức, không chặn ngoại lệ lịch sử cá nhân bằng điều kiện membership ACTIVE chung.
5. Admin archive/restore → chặn hoạt động chung và AI Tutor mới; notes/bookmarks/hội thoại cũ theo quyền cá nhân và grant nguồn.
6. Data request: chủ thể gửi yêu cầu, Admin xác minh/xử lý có audit; không tự động xóa toàn bộ.
7. Notifications/outbox idempotent; không rollback nghiệp vụ gốc nếu gửi notification lỗi.

## 7. Test bắt buộc
Admin-only create/enroll/teacher assignment/archive, cross-school/cross-class, AUTO/MANUAL sync/retry, bulk import duplicate/invalid, activation expiry/replay, JWT rotation/lock, transfer with pending assessment/submission, archive, historical read vs document grant, chat privacy, grade approval/audit, notification dedup, calendar LEARNING read-only. Integration test PostgreSQL thực.

### Thiết kế Core đích và chênh lệch triển khai
- Entity/quan hệ Classroom đã triển khai bằng migration 0008: School, AcademicYear, Semester, HomeroomClass, HomeroomRoster, Course/SubjectClass (`school_id`, grade_level, academic_year_id, semester_id, homeroom_class_id?, enrollment_mode AUTO|MANUAL), TeachingAssignment (PRIMARY|ASSISTING), ClassMembership (nguồn ghi danh, ACTIVE/ENDED, thời gian hiệu lực và từng đợt lịch sử). Identity sở hữu Student activation tokens; username unique cho Student, email nullable theo loại tài khoản.
- Phân công giáo viên và roster chỉ Admin mutation. Co-lecturer/owner invitation, ownership transfer, join request và Lecturer-created class ở thiết kế cũ **không còn là luồng MVP**. Archive/restore chỉ Admin. Đồng bộ AUTO không ghi đè lớp MANUAL; chuyển MANUAL→AUTO có preview/confirm.
- Access check tách `participate_current_class`, `read_own_history`, `read_document_source`, `use_ai_tutor`, `grade_submitted_work`. Transfer/archive fail closed cho hoạt động mới nhưng không chặn xem lịch sử hợp lệ.
- Identity chuyển đổi bằng migration mới 0005–0007: CORRECTION, username/email nullable/school_id/activated_at và Student token purposes. Không sửa migration cũ hoặc tự chuyển tài khoản/tạo trường; School thuộc Classroom chưa có FK. Backend kiểm tra school scope từ DB cho Admin helpers/API, fail closed khi thiếu/khác trường.
- Student dùng username, staff dùng email; login nhận đúng một identifier. Tài khoản có staff role dùng credential staff, không đi qua Student activation. Admin email invitation không nhận role STUDENT. Tài khoản Student legacy giữ UUID/hash/dữ liệu; Admin cùng trường gán username qua public helper, thu hồi phiên/token cũ và audit. ACTIVE/LOCKED đã verify email giữ trạng thái, đặt activated_at; pending vẫn phải kích hoạt. Không tự mở LOCKED hoặc thay username đã gán.
- Student recovery: Admin xác minh thủ công rồi yêu cầu cấp mã STUDENT_PASSWORD_RESET, hạn theo PASSWORD_RESET_EXPIRE_MINUTES (60 phút); backend yêu cầu identity_verified=true, thu hồi phiên và audit. Đây là xác nhận của Admin, không tự xác minh danh tính. Cấp lại mã vô hiệu hóa mã trước; create/issue-code/activate không cache response/mã. Chi tiết endpoint/public signatures theo API Contract/Core README. Bulk import và mapping School còn thuộc workflow Administration/Classroom tiếp theo.
- State machine cần bao phủ kích hoạt một lần, chuyển lớp có pending submission/attempt, archive chỉ Admin và approval assessment bởi giáo viên chính.
