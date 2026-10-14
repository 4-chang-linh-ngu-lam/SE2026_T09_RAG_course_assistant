# Core Service — Thiết kế v1

**Trạng thái:** BASELINE THIẾT KẾ · **Ngày:** 2026-10-11. Identity có triển khai và bằng chứng test tại TASK-001–004; các phần còn lại vẫn là thiết kế, chưa xác nhận toàn Core hoàn thành.

## 1. Công nghệ và xác thực
- Một Core FastAPI service, Next.js Web, PostgreSQL schema `core`, SQLAlchemy, Alembic, Docker Compose.
- Email/password; self-registration tạo Student, bắt buộc xác minh email. Admin tạo tài khoản bằng lời mời đặt mật khẩu, cấp Lecturer/Admin; không cho tự nâng quyền.
- JWT access **15 phút**, refresh **7 ngày**; refresh rotation, server lưu hash/phiên/revocation. Refresh cookie `HttpOnly; Secure; SameSite=Lax` trong mô hình cùng-site, access token giữ trong bộ nhớ client, không dùng localStorage. Hash password Argon2id.
- Khóa tài khoản, đổi mật khẩu, logout-all thu hồi phiên; backend kiểm tra trạng thái hiện hành. CSRF/Origin protection cho cookie mutations; rate limit login/register/reset/join code. Email verification/reset token một lần, hết hạn, lưu hash.
- Service-to-service access-check dùng service credential/scope riêng, không tin user_id từ browser.
- Access JWT có `sub` UUID, `roles`, `session_version`, `iat`, `exp`. Backend dùng role/status/session version hiện hành từ Identity public interface; role trong JWT không tự cấp quyền. Bootstrap đã nối Common lookup với Identity DB ở TASK-002; ứng dụng chưa nối vẫn từ chối an toàn.
- Token xác minh/reset lưu SHA-256, mặc định hết hạn sau 24 giờ/60 phút và cấu hình được. Refresh rotation giữ hạn gốc 7 ngày; dùng lại token revoked thu hồi family, không kéo dài hạn phiên. Logout thu hồi refresh hiện tại; logout-all/đổi mật khẩu/khóa tài khoản tăng session version và thu hồi toàn bộ refresh session.

## 2. Module và ownership
| Module | Trách nhiệm |
|---|---|
| identity | User, RoleAssignment, AuthSession, one-time token, DataRequest |
| classroom | Course, Class, Membership, JoinRequest, co-lecturer invitation, ownership |
| social/feed | ClassPost |
| social/comments | PostComment |
| social/calendar | CalendarEvent và bản chiếu deadline Learning |
| notification | Notification, trạng thái đã đọc, dedup |
| administration | Admin workflows, Core audit |
| common | DB, config, security, errors, shared dependencies |

Các module giao tiếp qua `public.py`; không import repository module khác. [Folder Structure](FOLDER_STRUCTURE.md).

Public Identity trả DTO an toàn, batch summary một query; Admin helpers kiểm tra actor/role/status hiện hành, ghi audit cùng transaction và hỗ trợ session caller sở hữu. Chữ ký/cách dùng tại [Core README](../../../../services/core/README.md#identity-public-interface-và-data-requests-task-004).

## 3. Schema logic (UUID PK, UTC timestamptz)
| Bảng | Trường chính | Constraint |
|---|---|---|
| users | id,email,display_name,password_hash,status,email_verified_at,session_version | email lowercase unique; status PENDING_VERIFICATION/ACTIVE/LOCKED; session_version mặc định 1 |
| role_assignments | user_id,role | unique(user_id,role); STUDENT/LECTURER/ADMIN |
| auth_sessions | id,user_id,refresh_hash,family_id,expires_at,revoked_at | refresh_hash unique; rotation atomically |
| one_time_tokens | id,user_id,purpose,token_hash,expires_at,consumed_at | token_hash unique |
| data_requests | id,user_id,request_type,reason,status,resolution_note,created_at,updated_at | ACCESS/EXPORT/DELETE; PENDING/IN_REVIEW/COMPLETED/REJECTED; FK user không cascade; index(user_id,id) |
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

## 4. State machine
- User: PENDING_VERIFICATION → ACTIVE ↔ LOCKED; LOCKED vô hiệu hóa phiên.
- Class: ACTIVE ↔ ARCHIVED; archived chỉ đọc, không thêm thành viên/bài đăng/bài nộp hoặc hỏi AI mới; ngoại lệ notes/bookmarks thuộc Document theo O2.
- JoinRequest: PENDING → APPROVED/REJECTED/CANCELLED; terminal. Bị từ chối hoặc tự rời có thể tạo request mới; bị REMOVED chỉ tham gia lại khi giảng viên cho phép.
- Membership: ACTIVE → LEFT/REMOVED; tái tham gia tạo record mới, giữ lịch sử. Một ACTIVE/class/user.
- Transfer owner: chỉ OWNER hoặc Admin can thiệp chuyển cho CO_LECTURER ACTIVE; một transaction đổi owner và membership roles, audit; không bao giờ có hai OWNER. OWNER phải transfer trước khi rời.
- Approve/reject/remove cạnh tranh dùng transaction, row locking/unique constraints; approve lặp APPROVED trả 200 không tạo trùng, trạng thái terminal khác trả 409.

## 5. Quyền
| Hành động | Admin | Owner | Co-lecturer | Student ACTIVE |
|---|---|---|---|---|
| Tạo lớp | Can thiệp quản trị; có role LECTURER để tạo lớp riêng | Có | Có nếu là Lecturer | Không |
| Duyệt/loại Student | Can thiệp + audit | Có | Có | Không |
| Mời co-lecturer/transfer | Can thiệp + audit | Có | Không | Không |
| Archive/restore | Can thiệp + audit | Có | Không | Không |
| Post/comment | Chỉ khi là thành viên phù hợp | Có | Có | Có |
| Ẩn/xóa nội dung vi phạm | Can thiệp + audit | Có | Có | Chỉ nội dung mình |
| Xem lớp | Không mặc định; can thiệp có lý do/audit | Có | Có | Có |
| Xem chat riêng tư | Không mặc định | Không mặc định | Không mặc định | Chủ chat |

Mọi request kiểm tra role + membership ACTIVE + class status + action; quyền lịch sử không tự cấp quyền hiện hành. Người rời lớp vẫn có quyền giới hạn xem/appeal điểm theo M1/O4 qua Learning.

## 6. Luồng
1. Register → verify email → ACTIVE; Admin create → set-password invitation.
   Lời mời ADMIN_INVITATION một lần (mặc định 24 giờ, cấu hình được) được chấp nhận qua password/reset; đặt mật khẩu và xác minh email cho PENDING, không mở tài khoản LOCKED.
2. Login → access JWT + refresh cookie; refresh rotation; logout/revoke và khóa tài khoản chặn phiên.
3. Join code → PENDING → lecturer approve → membership ACTIVE → outbox notification.
4. Feed/comments: kiểm tra membership/status, soft delete và audit.
5. Calendar: CORE event được chỉnh bởi lecturer; LEARNING deadline chỉ phản chiếu event versioned, thay deadline phải thông báo.
6. Admin lock/role/class intervention và xử lý yêu cầu dữ liệu cá nhân; báo cáo tổng hợp nhiều service tích hợp ở G5.
7. Notification dùng outbox/dedup, lỗi gửi không rollback nghiệp vụ gốc.
8. User tạo/xem data requests của chính mình; chỉ ghi PENDING, không tự xóa/xuất dữ liệu. Administration xử lý thủ công theo K1/K4/O8; retention cụ thể cần người vận hành duyệt.

## 7. Test bắt buộc
Cross-class, PENDING/LEFT/REMOVED/LOCKED, archived, owner transfer, concurrent approve, JWT refresh replay/revoke, CSRF/rate limit, feed delete, notification dedup, calendar LEARNING read-only, Admin audit. Mọi endpoint có permission/contract test; integration test dùng PostgreSQL thực.

## Phạm vi chính khóa THCS/THPT và thay đổi cần triển khai
- Role kỹ thuật hiện tại `ADMIN`, `LECTURER`, `STUDENT` **giữ nguyên** để không phá vỡ Identity đã triển khai; tên UI lần lượt là Quản trị viên, Giáo viên, Học sinh. Không thêm Parent hoặc School Admin trong MVP.
- Lớp học là **lớp môn học chính khóa** của khối 6–12, cần có môn học, khối, năm học và tham chiếu lớp hành chính nếu có. Trường và phân công giáo viên cần được mô hình hóa/kiểm tra ở bước Classroom; **schema `courses/classes` hiện liệt kê chưa có đủ metadata này**.
- Ghi danh có thể do giáo viên/Admin thực hiện theo phân công hoặc qua mã lớp và phê duyệt nếu bật. Học sinh **không được tự rời** lớp chính khóa. Các state machine, permission checks, audit và API phải được cập nhật cùng migration/test trước khi phát hành.
- Giáo viên chỉ tạo và quản lý lớp trong phạm vi phân công được xác minh; cách xác minh phân công còn cần quyết định cụ thể, không giả định tự do tạo mọi lớp.
- Luồng self-registration/email verification hiện đã triển khai cho role `STUDENT`; chưa được xác nhận phù hợp onboarding người chưa thành niên. Cần chốt cơ chế cấp tài khoản, quyền đại diện/đồng ý khi cần, bảo vệ dữ liệu học sinh và test trước khi cho người dùng thực tế đăng ký.
- Các bảng Identity/migration đã áp dụng không được sửa lịch sử. Thay đổi schema phải qua Alembic revision mới, API version/contract và test quyền tương ứng.
