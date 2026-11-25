# Tiêu chí nghiệm thu đề xuất
Chưa chạy test; kế thừa DOC-T06. Unit, contract, integration PostgreSQL thật, E2E, fault injection. Mỗi AC cần bằng chứng.
| ID | Điều kiện đạt |
|---|---|
| C-AC01 | Register hợp lệ, email trùng bị chặn kể cả concurrent |
| C-AC02 | Login đúng/sai, rate limit, không lộ hash |
| C-AC03 | Refresh rotation concurrent, reuse detection, logout revoke |
| C-AC04 | Suspend/delete pending chặn quyền dù JWT cũ còn hạn |
| C-AC05 | Tạo lớp atomic với đúng một owner |
| C-AC06 | Invite hợp lệ/hết hạn/thu hồi, join trùng không nhân membership |
| C-AC07 | Transfer owner atomic, owner không rời trước transfer |
| C-AC08 | Remove member thu hồi quyền mới tại Document/Learning/AI |
| C-AC09 | Archive chỉ đọc, restore đúng quyền |
| C-AC10 | Outsider và student không leo quyền |
| C-AC11 | Feed/comment đúng quyền, moderation có audit |
| C-AC12 | Internal API từ chối user JWT, sai audience/scope/expired |
| C-AC13 | Authorization action đúng role, Core offline fail closed ở consumer |
| C-AC14 | Outbox atomic, restart recovery, duplicate delivery dedup |
| C-AC15 | Notification offline không chặn post |
| C-AC16 | AI/Document/Learning offline không chặn Core độc lập |
| C-AC17 | Deletion job từng đích, không DELETED sớm, retry an toàn |
| C-AC18 | Frontend tương thích và error envelope nhất quán |
| C-AC19 | Không truy cập DB xuyên service, không leak secrets |
| C-AC20 | Real integration authorization và event delivery |
DoD: static/unit/contract/integration phù hợp, không skip vô lý, evidence mock/real riêng, TL review. Load test 358 user theo workload được chốt, không đồng nhất với 358 inference.