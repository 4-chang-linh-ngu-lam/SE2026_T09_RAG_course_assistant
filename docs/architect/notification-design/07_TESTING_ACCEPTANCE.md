# 20 AC — chưa verified
| ID | Điều kiện |
|---|---|
| N-AC01 | Event hợp lệ durable trước 202 |
| N-AC02 | Invalid schema/type/version reject |
| N-AC03 | Duplicate cùng payload idempotent |
| N-AC04 | Cùng ID khác payload 409 |
| N-AC05 | Worker restart recovery |
| N-AC06 | Lease fencing |
| N-AC07 | Retry/backoff dependency outage |
| N-AC08 | Fanout replay không trùng |
| N-AC09 | Membership hiện hành |
| N-AC10 | Assignment recipient/completion đúng |
| N-AC11 | Preferences/mandatory policy đúng |
| N-AC12 | List pagination và unread count |
| N-AC13 | Mark read idempotent |
| N-AC14 | Read-all đúng user |
| N-AC15 | Delete/preference update đúng user, không resurrect khi replay |
| N-AC16 | Chặn cross-user access |
| N-AC17 | Chặn user JWT/sai service scope/source, không leak nội dung |
| N-AC18 | Account deletion completion đúng |
| N-AC19 | Core/Learning outbox khi Notification offline, recovery |
| N-AC20 | Real cross-service event -> frontend notification |
Unit/contract/integration PostgreSQL/E2E/fault injection; evidence, TL review; polling load benchmark theo workload. Chi tiết AC đề xuất từ nhóm accepted.