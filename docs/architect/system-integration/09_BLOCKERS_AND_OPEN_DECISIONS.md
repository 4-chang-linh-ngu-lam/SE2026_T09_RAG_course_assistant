# Blockers và open decisions
| ID | Vấn đề | Owner đề xuất | Gate |
|---|---|---|---|
| B01 | DOC-01/02 PostgreSQL migration, ACL/concurrency và storage-volume restart verification bị chặn bởi SERVER-01; local engineering đã accepted | TL | Testing verification |
| B02 | Core ID/schema/migration/RBAC và frontend routes thực tế | TL | contract freeze |
| B03 | Provision Service JWT keys/trust maps, approve rotation runbook and migrate callers to shared `lumi-service-auth` | TL + service owners | real integration |
| B04 | AI HTTP adapters, durable job, index readiness/deletion | AI team + TL | DOC-13/LRN-14 |
| B05 | D6 nguyên văn, cross-class/streaming/HINT_ONLY | TL + AI | D6 acceptance |
| B06 | Document durable deletion/cleanup, active index identity, stale job fencing | TL + AI | deletion/activation |
| B07 | Account deletion completion, H1 teacher replacement semantics, retention 14 ngày áp dụng phạm vi nào | TL + all services | deletion acceptance |
| B08 | Learning deadline/late/reopen/rounding/recipient snapshot | TL | Learning implementation liên quan |
| B09 | Notification recipient API, mandatory types, dedup horizon, Document event names | TL | Notification acceptance |
| B10 | QA gốc, workload/SLO, RPO/RTO, VPS real AI sizing | TL + team | system acceptance |
| B11 | RAG-D02 canonical nội bộ deferred | AI/RAG team | AI internal design |
| B12 | CI/test inventory discrepancy và evidence hiện trạng | TL + team | baseline |
Không tự giải quyết blocker bằng giả định. Đối chiếu business rules A–M và QA gốc; ghi decision mới khi cần. Các tài liệu service là thiết kế mục tiêu, không xác nhận code. Không sửa application code/merge/deploy trong lượt này.
