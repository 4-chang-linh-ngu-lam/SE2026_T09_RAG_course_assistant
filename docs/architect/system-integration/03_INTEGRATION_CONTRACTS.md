# Cross-service contracts
| Caller | Sync | Async |
|---|---|---|
| Core | — | deletion workflow tới Document/Learning/AI/Notification; events Notification |
| Document | Core | AI ingestion/deletion; Notification events |
| Learning | Core, Document | AI generation/grading; Notification events |
| AI | Core, Document, Learning D6 | — |
| Notification | Core, Learning, Document khi cần | — |
Async REST: durable 202, idempotency key, poll, lease/fencing, retry/backoff+jitter, no duplicate execution on unknown outcome. Outbox/inbox: CORE-T06 envelope event_id,event_type,event_version,source,occurred_at,request_id,payload; ack != completion. Per-target delivery state. Không HTTP trong DB transaction, tránh synchronous call cycles.
Contracts cần freeze: Core POST /internal/v1/authorization/check; Document rag-scope/validate/file; AI ingestion/status/deletion và generation/grading; Learning POST /internal/v1/assessment-policy/check; Notification POST /internal/v1/events. Recipient lookup và deletion completion chưa chốt. Error envelope DOC-T03, X-Request-ID, versioned DTO/OpenAPI, contract tests. AI team phải xác nhận adapters, durable jobs, index readiness, scope/D6 enforcement. TL có thể bổ sung adapter nếu thiếu, không tự quyết thuật toán RAG.