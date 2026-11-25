# Public API — CORE-T02
Prefix /api/v1 mục tiêu, đối chiếu routing/frontend trước thay đổi.
| Method | Path |
|---|---|
| POST | /auth/register, /auth/login, /auth/refresh, /auth/logout |
| GET PATCH DELETE | /users/me |
| GET POST | /classrooms |
| GET PATCH DELETE | /classrooms/{id} |
| POST | /classrooms/{id}/archive, /classrooms/{id}/restore, /classrooms/join |
| GET POST | /classrooms/{id}/invites |
| DELETE | /classrooms/{id}/invites/{iid} |
| GET | /classrooms/{id}/members |
| PATCH DELETE | /classrooms/{id}/members/{uid} |
| POST | /classrooms/{id}/leave, /classrooms/{id}/transfer-owner |
| GET POST | /classrooms/{id}/posts |
| GET PATCH DELETE | /posts/{id} |
| GET POST | /posts/{id}/comments |
| PATCH DELETE | /comments/{id} |
| POST | /reports |
| GET | /admin/reports, /admin/users |
| PATCH | /admin/reports/{id}, /admin/users/{id}/status |
DTO chi tiết và pagination cần đối chiếu hiện trạng. Đề xuất 201 create, 202 deletion request, 204 delete/logout, 401 unauthenticated, 403 forbidden, 404 che tài nguyên, 409 conflict, 422 validation, 429 rate limit, 503 dependency unavailable. Error envelope DOC-T03; không trả password/token hash. Actor lấy từ token đã xác minh, không tin body.