# Core API Contract v1

**Trạng thái:** BASELINE HỢP ĐỒNG · **Ngày:** 2026-10-11. API chưa được xác nhận đã triển khai. Business Rules ưu tiên khi có xung đột.

## Quy ước
- Public `/api/v1`, HTTP/JSON, Bearer access JWT; refresh/logout qua HttpOnly Secure cookie + CSRF/Origin protection.
- UUID cho ID; ISO-8601 UTC cho thời gian. List: `?limit=20&cursor=<opaque>`, limit 1..100; `{"items":[],"next_cursor":null}`.
- `200` đọc/cập nhật, `201` tạo, `204` xóa; lỗi `400 BAD_REQUEST`, `401 UNAUTHENTICATED`, `403 FORBIDDEN`, `404 NOT_FOUND`, `409 CONFLICT`, `422 VALIDATION_ERROR`, `429 RATE_LIMITED`.
- Error: `{"error":{"code":"FORBIDDEN","message":"Không có quyền","correlation_id":"uuid"}}`. Che tài nguyên ngoài quyền bằng 404.
- Mutations hỗ trợ `Idempotency-Key` UUID (scope user+endpoint, giữ 24h); cùng key khác payload trả 409. Mọi API nội dung lớp kiểm tra membership hiện hành và status.

## Auth / User
| Method | Endpoint | Quyền / Body → Kết quả |
|---|---|---|
| POST | /auth/register | Public; {email,password} → 201 {user_id,status:PENDING_VERIFICATION} |
| POST | /auth/verify-email | Public; {token} → 200 {verified:true} |
| POST | /auth/login | Public; {email,password} → 200 {access_token,token_type:bearer,expires_in:900} + refresh cookie |
| POST | /auth/refresh | Refresh cookie + CSRF → 200 access + rotated cookie |
| POST | /auth/logout | Refresh cookie + CSRF → 204, revoke/clear |
| POST | /auth/logout-all | Bearer → 204 |
| POST | /auth/password/forgot | Public; {email} → 200 generic |
| POST | /auth/password/reset | Public; {token,new_password} → 204 |
| GET/PATCH | /users/me | Bearer; GET profile, PATCH {display_name?} |
| GET/POST | /users/me/data-requests | Bearer; GET list, POST {type:ACCESS/EXPORT/DELETE,reason?} → 201 PENDING |

## Course / Class / Membership
| Method | Endpoint | Quyền / tác dụng |
|---|---|---|
| POST/GET | /courses | Lecturer/Admin tạo {code,name}; authenticated list |
| POST/GET | /classes | Lecturer tạo {course_id,name}; authenticated list lớp có quyền |
| GET/PATCH | /classes/{class_id} | ACTIVE member xem; Owner/Admin cập nhật {name?,join_enabled?} |
| POST | /classes/join-requests | Student {join_code} → 201 {request_id,class_id,status:PENDING} |
| GET | /classes/{class_id}/join-requests | Owner/Co-lecturer/Admin |
| POST | /classes/{class_id}/join-requests/{id}/approve | Owner/Co-lecturer/Admin → 200 ACTIVE membership |
| POST | /classes/{class_id}/join-requests/{id}/reject | Owner/Co-lecturer/Admin → 200 REJECTED |
| POST | /classes/{class_id}/join-requests/{id}/cancel | Request owner → 200 CANCELLED |
| GET | /classes/{class_id}/members | ACTIVE member / Admin intervention |
| DELETE | /classes/{class_id}/members/me | Student; Owner chỉ sau transfer → 204 |
| DELETE | /classes/{class_id}/members/{user_id} | Owner/Co-lecturer/Admin → 204 |
| POST | /classes/{class_id}/co-lecturers/invitations | Owner/Admin {lecturer_id} → 201 |
| POST | /classes/{class_id}/co-lecturers/invitations/{id}/accept | Invitee → 200 |
| POST | /classes/{class_id}/co-lecturers/invitations/{id}/reject | Invitee → 200 |
| POST | /classes/{class_id}/ownership-transfer | Owner/Admin {new_owner_user_id} → 200 |
| POST | /classes/{class_id}/archive | Owner/Admin → 200 ARCHIVED |
| POST | /classes/{class_id}/restore | Owner/Admin → 200 ACTIVE |

Approve lặp đã APPROVED trả 200 cùng membership, terminal khác trả 409; không tạo trùng. Bị REMOVED cần giảng viên cho phép trước khi vào lại.

## Feed / Comments / Calendar / Notifications
| Method | Endpoint | Quyền / Body |
|---|---|---|
| GET/POST | /classes/{class_id}/posts | ACTIVE member; POST {body} |
| PATCH/DELETE | /classes/{class_id}/posts/{post_id} | Author hoặc lecturer moderation |
| GET/POST | /classes/{class_id}/posts/{post_id}/comments | ACTIVE member; POST {body} |
| PATCH/DELETE | /classes/{class_id}/posts/{post_id}/comments/{id} | Author hoặc lecturer moderation |
| GET | /classes/{class_id}/calendar | ACTIVE member; ?from=ISO&to=ISO |
| POST | /classes/{class_id}/calendar | Owner/Co-lecturer; {title,starts_at,ends_at} |
| PATCH/DELETE | /classes/{class_id}/calendar/{id} | Owner/Co-lecturer; chỉ CORE-origin event |
| GET | /notifications | Authenticated; chỉ của mình, paginated |
| PATCH | /notifications/{id}/read | Recipient → 200 {read:true} |
| POST | /notifications/read-all | Authenticated → 204 |

Soft delete bài đăng/bình luận ẩn khỏi danh sách; archived từ chối hoạt động ghi chung. Deadline LEARNING chỉ đồng bộ qua integration, không chỉnh tại Core.

## Admin / Internal
| Method | Endpoint | Quyền / Body |
|---|---|---|
| POST | /admin/users | Admin {email,roles} → 201, gửi link đặt mật khẩu |
| PATCH | /admin/users/{id}/status | Admin {status:ACTIVE/LOCKED} + audit |
| PUT | /admin/users/{id}/roles | Admin {roles:[...]} + audit; không xóa Admin cuối |
| GET | /admin/audit-events | Admin; paginated redacted audit |
| GET/PATCH | /admin/data-requests/{id} | Admin; PATCH {status:IN_REVIEW/COMPLETED/REJECTED,resolution_note} |
| GET | /admin/data-requests | Admin; paginated |
| GET | /internal/v1/classes/{class_id}/access?user_id=&action= | Authenticated service scope core:check_access → {allowed,class_id,user_id,action} |

Admin can thiệp lớp cần `X-Admin-Reason` và audit; không tự có quyền xem chat riêng tư. Internal API không chấp nhận browser trực tiếp; fail closed.

## Validation / Contract tests
- Email chuẩn hóa lowercase; mật khẩu 12..128 ký tự; body post/comment 1..10000, title/name 1..200; starts_at < ends_at. Không expose password_hash, refresh_hash, join_code_hash.
- Test: unauthorized/cross-class, PENDING/LEFT/REMOVED/LOCKED/archived, concurrent approve, ownership, JWT replay/revoke, CSRF, post/comment delete, notification dedup, calendar LEARNING read-only, Admin audit, internal auth.
- FastAPI phải sinh OpenAPI phản ánh request/response/error schemas cho từng endpoint; CI kiểm tra contract snapshot. **Bảng endpoint và DTO trên là hợp đồng hành vi, không phải bằng chứng đã có OpenAPI chạy thực tế.**
