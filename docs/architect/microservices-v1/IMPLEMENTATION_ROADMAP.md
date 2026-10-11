# Lộ trình — Core hoàn chỉnh trước

**Trạng thái:** BASELINE KẾ HOẠCH · **Ngày:** 2026-10-11. Các giai đoạn là tiêu chí để nghiệm thu, không phải đã hoàn thành.

| Giai đoạn | Phạm vi | Điều kiện chuyển |
|---|---|---|
| **G0 — Contract Core** | ERD, state machines, RBAC, API, folder ownership, mock | Nhóm review hợp đồng và phân công |
| **G1 — Core chức năng đầy đủ** | Identity/JWT, user/role, classroom/membership, co-lecturer/transfer/archive, feed/comments/calendar, notification, Core admin/audit | Web → Core → DB thực hiện được các luồng, có test quyền |
| **G2 — Core tích hợp** | Compose, migration, CI, health, security, concurrency, API/contract/integration test | Demo toàn bộ Core trên môi trường sạch, có bằng chứng kiểm thử |
| **G3 — Document + AI** | File/version/grant/processing, source-bound notes/bookmarks, RAG Tutor | Quyền nguồn, thu hồi, citation/abstention được kiểm thử |
| **G4 — Learning** | Practice, Assessment, Assignment, grading, deadlines, appeal | Test deadline, attempt/version, audit, sửa điểm |
| **G5 — Learner Intelligence + MVP** | Evidence/mastery/recommendations, dashboard, báo cáo PDF/Excel và tích hợp | Kiểm tra Business Rules và Quality Attributes |

**Không chuyển G3 khi chỉ hoàn thành Core Foundation.** Notes/bookmarks gắn nguồn thuộc Document ở G3; báo cáo tổng hợp nhiều service được tích hợp G5, không loại khỏi MVP.

## Phân công G1–G2
- TV1: Identity/auth/security; TV2: Classroom/membership/permission.
- TV3: Social (feed/comments/calendar); TV4: Notification/administration/audit, CI và test tích hợp.
- Mỗi người thực hiện UI/API/test theo feature; shared files có reviewer; contract/mock cho phép làm song song.

## Thứ tự thực hiện
1. Chốt API/ERD/quyền và mock; tạo skeleton.
2. Dựng auth, database, migration, frontend shell.
3. Hoàn thiện identity/classroom public interface, triển khai social/notification/admin song song.
4. Tích hợp từng luồng, test cross-class, locked, archived, ownership, concurrent requests.
5. Chạy Compose từ môi trường sạch, CI, security/contract tests, lưu kết quả rồi mới sang G3.

## Checklist nghiệm thu Core
- [ ] Register/verify/login/refresh/logout/revoke, Admin account/roles/lock.
- [ ] Class, join/approve/reject/leave/remove, co-lecturer, transfer, archive/restore.
- [ ] Feed/comments/calendar/notifications và Core admin/audit end-to-end.
- [ ] OpenAPI, migration, Compose, health, CI, test quyền/tích hợp có bằng chứng.

[Core Design](core/DESIGN.md) · [Core API](core/API_CONTRACT.md) · [Quality Attributes](QUALITY_ATTRIBUTES.md).
