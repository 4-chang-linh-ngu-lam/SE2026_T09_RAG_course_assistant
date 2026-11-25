# Roadmap — LRN-T10
| Task | Nội dung | Phụ thuộc đề xuất |
|---|---|---|
| LRN-00 | Discovery code/business rules/AC/gap | — |
| LRN-01 | DB/migration | 00 |
| LRN-02 | Core authorization | 00,01 |
| LRN-03 | Question bank/version | 01,02 |
| LRN-04 | Assessment engine | 03 |
| LRN-05 | Assignment/publication | 04 |
| LRN-06 | Attempt/autosave/submit | 05 |
| LRN-07 | Grading/audit | 06 |
| LRN-08 | Practice | 04,06,07 |
| LRN-09 | AI client/durable worker | 02,03,07 |
| LRN-10 | D6 protection | 02,06 |
| LRN-11 | Analytics/recommendation | 07,08 |
| LRN-12 | Notification outbox | 01,05,07 |
| LRN-13 | Frontend integration | 02–12 |
| LRN-14 | Security/integration/acceptance | 01–13 |
Discovery trước code, reuse tương thích. LRN-05/07 phải có outbox trước nghiệm thu publication; LRN-10 cần D6 gốc và AI agreement; LRN-09 real AI phụ thuộc AI team, mock trước. Không expose API thiếu auth. AC mapping chi tiết sau discovery. Preflight Git, scope, test, evidence, TL review; không auto commit/push/merge/deploy. Open: physical schema, DTO, recipient snapshot, late/reopen/rounding, retention, D6 cross-class/streaming, AI contracts.