# Roadmap đề xuất
CORE-00 discovery trước code: inventory, schema/API/auth hiện có, business rules, gap, AC matrix, migration risk, revised backlog. Không viết lại code tương thích.
| Task | Nội dung | Phụ thuộc | AC |
|---|---|---|---|
| CORE-01 | DB/migration và constraints | 00 | 01,05,06,07,19 |
| CORE-02 | Auth/session/security | 01 | 01–04 |
| CORE-03 | Classroom/membership/invite/transfer | 01,02 | 05–10 |
| CORE-04 | Internal authorization + service auth | 02,03 | 08,10,12,13 |
| CORE-05 | Feed/comment/moderation | 03 | 11,15 |
| CORE-06 | Outbox/delivery worker | 01,04 | 14,15,16 |
| CORE-07 | Account deletion orchestration | 04,06 | 04,17 |
| CORE-08 | API/frontend compatibility | 02–07 | 18 |
| CORE-09 | Integration/security/fault/load | 01–08 | 01–20 |
CORE-05 phải tích hợp outbox trước khi nghiệm thu; không expose API thiếu security. CORE-07 bị chặn bởi policy retention/owner và completion contract. CORE-09 real integration phụ thuộc service đích. Mỗi task preflight Git, scope, tests, evidence, TL review; không auto commit/push/merge/deploy. Backlog và AC đề xuất chưa kiểm thử, không tự sửa architecture đã accepted.