# Tiêu chí nghiệm thu đề xuất
Kế thừa DOC-T06. Unit, contract, integration PostgreSQL thật, E2E, fault injection. Mỗi AC cần bằng chứng.
| ID | Điều kiện đạt |
|---|---|
| C-AC01 | Register hợp lệ, email trùng bị chặn kể cả concurrent |
| C-AC02 | Login đúng/sai, rate limit, không lộ hash |
| C-AC03 | Refresh rotation concurrent, reuse detection, logout revoke |
| C-AC04 | Suspend/delete pending chặn quyền dù JWT cũ còn hạn |
| C-AC05 | Admin creates class atomically with exactly one active PRIMARY TeachingAssignment; no OWNER class role |
| C-AC06 | Only actor allowed by Business Rules mutates roster; self-join/join-code denied with permission test |
| C-AC07 | Admin changes PRIMARY/ASSISTING per H1; replacement-before-exit per H2; no owner-transfer API |
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

## CORE-04 local coverage

CORE-T03 route/action registry có unit/contract/security coverage tại `services/core/tests/classroom/test_authorization.py`, `test_contract.py` và `tests/security/test_service_jwt.py`. Local targeted results và command/exit code được ghi trong [CORE-04 Implementation Report](10_CORE04_IMPLEMENTATION_REPORT.md). Chúng không chứng minh Document/Learning/AI consumer integration hoặc AC20; AC10/12 server verification và real consumer acceptance vẫn riêng biệt.

## CORE-CR01/02 AC supersession

C-AC05/06/07 text above supersedes the old owner/invite/transfer checks. Preserve IDs for traceability. C-AC01 register-valid remains a separate mismatch with Business Rules/API Contract; it is not changed by CORE-CR01/02 and needs Technical Lead disposition.
