# Roadmap đề xuất — CORE-T01–08 sau CORE-CR01–04

CORE-00 discovery trước code; giữ implementation hiện hành nếu compatible. CORE-CR01–04 là design correction accepted, chưa tự động là implementation complete.

| Task | Nội dung sau correction | Disposition hiện tại | Dependency / AC |
|---|---|---|---|
| CORE-00 | Inventory, authorization mapping, Business Rules conflict, migration/test/gap report | DISCOVERY APPROVED | — |
| CORE-01 | Verify schema/migrations hiện có; additive delta chỉ khi được duyệt | VERIFY / DEFER | 00; AC 01,05–07,19 |
| CORE-02 | Reuse Identity user-auth/session; consume shared SYS-02 only for service identity | REUSE | SYS-02; AC 01–04 |
| CORE-03 | Reuse Admin class/roster/AUTO-MANUAL/PRIMARY-ASSISTING; preserve Business Rules | REUSE + VERIFY | 01–02; AC 05–10 |
| CORE-04 | CORE-T03 generic POST adapter/action registry + shared Service JWT | EXTEND | SYS-02, CORE-02/03; AC 08,10,12,13 |
| CORE-05 | Reuse feed/comment/moderation | REUSE | CORE-03; AC 11,15 |
| CORE-06 | Reuse outbox producers; extend per-target delivery to Notification Service | EXTEND | CORE-01/04, NTF-T03; AC 14–16 |
| CORE-07 | Distributed account deletion after retention/owner/completion policy | DEFER | CORE-04/06, service contracts; AC 04,17 |
| CORE-08 | Verify frontend/API and gateway compatibility | VERIFY | CORE-02–07, SYS-03/04; AC 18 |
| CORE-09 | Cross-service/security/fault/load acceptance | DEFER | CORE-01–08 + service environments; AC 01–20 |

CORE-03 does not implement join/invite/self-leave or class OWNER. CORE-04 keeps check_class_action as policy logic behind the new REST adapter; no cross-service imports. CORE-06 does not move Core tables into Notification. CORE-07 remains blocked by retention and per-target completion contract. No task starts from this roadmap.
