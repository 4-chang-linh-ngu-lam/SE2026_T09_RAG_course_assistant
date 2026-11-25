# 8 tasks
| Task | Nội dung | Dependency đề xuất |
|---|---|---|
| NTF-00 | Discovery code/business rules | — |
| NTF-01 | DB/migration | 00 |
| NTF-02 | Internal event inbox + service auth | 01 |
| NTF-03 | Durable worker/dedup | 02 |
| NTF-04 | Recipient resolution/templates | 03, Core/Learning contracts |
| NTF-05 | Public API/preferences | 01, auth |
| NTF-06 | Frontend notification center | 04,05 |
| NTF-07 | Integration/security/acceptance | 01–06 |
Discovery trước code, reuse hiện có. Không expose API thiếu auth. Deletion workflow, retention, mandatory types, recipient APIs và Document events cần chốt trước nghiệm thu liên quan. Mock trước, real integration bắt buộc. Preflight Git, scope, test, evidence, TL review; không auto commit/push/merge/deploy.