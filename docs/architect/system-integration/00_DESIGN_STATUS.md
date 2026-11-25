# System Integration — ACCEPTED 25/11/2026
Người dùng phê duyệt SYS-D01–05 và SYS-T01–07.
| ID | Quyết định |
|---|---|
| SYS-D01 | 5 microservices, monorepo; RAG library trong AI |
| SYS-D02 | Nginx reverse proxy, HTTPS, public route allowlist |
| SYS-D03 | REST sync, durable async REST/polling, outbox/inbox |
| SYS-D04 | PostgreSQL instance chung, database/credential riêng; AI storage tự quyết |
| SYS-D05 | User JWT + Service JWT, Core và resource authorization |
| SYS-T01 | Docker Compose VPS, không Kubernetes Increment 1 |
| SYS-T02 | Dev/Test/Prod tách biệt |
| SYS-T03 | Structured logs, request ID, health, metrics |
| SYS-T04 | GitHub Actions, merge commit, review và deploy gates |
| SYS-T05 | Load test 358 concurrent users; workload/SLO đề xuất cần đối chiếu |
| SYS-T06 | Backup/restore/rollback, daily backup đề xuất |
| SYS-T07 | Master roadmap phase 0–5, 24 system AC |
Thiết kế mục tiêu, chưa xác minh toàn bộ code/business rules, chưa test/deploy. 72 quyết định thuộc Document/Core/Learning/Notification/System được phê duyệt; RAG-D01 riêng, RAG-D02 deferred. Không coi design accepted là implementation accepted.