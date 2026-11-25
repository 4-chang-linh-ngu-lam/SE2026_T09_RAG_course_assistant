# Public API
Prefix /api/v1 mục tiêu, đối chiếu frontend.
| Method | Path |
|---|---|
| GET | /notifications |
| GET | /notifications/unread-count |
| PATCH | /notifications/{id}/read |
| POST | /notifications/read-all |
| DELETE | /notifications/{id} |
| GET | /notification-preferences |
| PUT | /notification-preferences |
DTO notification id,type,title,body,resource_type,resource_id,created_at,read_at. Actor từ verified JWT, chỉ thao tác notification của mình. Pagination/error envelope DOC-T03; read/read-all idempotent; không lộ nội dung nhạy cảm. Preferences mặc định bật, loại bắt buộc không tắt; danh sách cần chốt.