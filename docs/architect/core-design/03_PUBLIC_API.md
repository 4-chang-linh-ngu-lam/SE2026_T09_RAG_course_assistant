# Public API — CORE-T02

CORE-T02 giữ prefix /api/v1 và tương thích frontend. Chi tiết method/DTO/status/error chuẩn là docs/architect/microservices-v1/core/API_CONTRACT.md.

| Nhóm | Route contract hiện hành | Quyền |
|---|---|---|
| Identity | /auth/login, /refresh, /logout, /activate, /password/*, /users/me | Theo user status/role; public /auth/register BLOCKED — LEGACY |
| Catalog/class create | /admin/catalog, /admin/courses, /admin/homeroom-classes, /admin/classes | Admin cùng trường |
| Roster/enrollment | /admin/homeroom-classes/*/roster, /admin/classes/*/members, enrollment preview/mode/sync/transfer | Admin; AUTO/MANUAL, version guard, giữ history |
| Teaching assignments/lifecycle | /admin/classes/{id}/teaching-assignments, /admin/classes/{id}/archive, /restore | Admin; PRIMARY/ASSISTING và audit |
| Class reads | GET /classes, /classes/{id}, /classes/{id}/members | Current school/membership/teaching assignment |
| Social | /classes/{id}/posts, /posts/{id}/comments, /classes/{id}/calendar | Core permission/audit/no-store |
| Notification hiện hành | /notifications, /notifications/{id}/read, /notifications/read-all | Hiện do Core module phục vụ; gateway chuyển ownership theo NTF migration contract |

## Draft routes superseded bởi CORE-CR01/02

| Draft route | Disposition |
|---|---|
| /classrooms, /classrooms/join, /classrooms/{id}/invites | Không phải route Lumi hiện hành; dùng Admin catalog/class/roster |
| /classes/join-requests* | Out of MVP theo A6 |
| /classrooms/{id}/leave, /classes/{id}/members/me | Out of MVP theo A5 |
| /classrooms/{id}/transfer-owner, /classes/{id}/ownership-transfer | Superseded theo H1/CORE-CR02 |
| Lecturer POST /classes; Owner archive/restore | Superseded; Admin quản lý class/assignment/lifecycle |

Giữ trace các CORE-T02 route draft để review lịch sử, nhưng không implement/expose alias, invitation, self-join, self-leave hoặc owner-transfer.
