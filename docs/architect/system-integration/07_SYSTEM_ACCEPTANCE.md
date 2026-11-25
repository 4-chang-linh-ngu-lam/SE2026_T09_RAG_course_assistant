# 24 system AC — chưa verified
| ID | Điều kiện |
|---|---|
| S-AC01 | HTTPS và public routing đúng service |
| S-AC02 | Nested classroom routes đúng, không shadow |
| S-AC03 | Internal/DB ports không public, bypass bị chặn |
| S-AC04 | User JWT auth/refresh và revoked account |
| S-AC05 | Service JWT scope/audience/expiry/source |
| S-AC06 | Current membership + resource authorization |
| S-AC07 | D6 enforcement và fail closed |
| S-AC08 | Database/credentials tách biệt |
| S-AC09 | Không cross-service SQL/FK |
| S-AC10 | Persistent data qua restart/migration |
| S-AC11 | Real upload -> index -> grounded QA/citation |
| S-AC12 | Version switch/revoke/delete không stale access |
| S-AC13 | Real AI generation/grading -> Learning validation |
| S-AC14 | Outbox -> inbox -> notification, dedup và deletion completion |
| S-AC15 | AI offline không chặn nghiệp vụ độc lập |
| S-AC16 | Notification offline, recovery event |
| S-AC17 | Core outage fail closed; durable jobs recover |
| S-AC18 | Compose reproducible dev/test/prod isolation |
| S-AC19 | CI gates, image SHA, contract compatibility |
| S-AC20 | Smoke, health, logs/request ID, deploy approval |
| S-AC21 | 358-user workload và SLO được chốt |
| S-AC22 | Không mất acknowledged data dưới tải/fault |
| S-AC23 | Restore DB/file/index consistency |
| S-AC24 | Rollback/forward-fix tương thích migration |
Unit/contract/integration/E2E/fault/load/restore evidence. Mock không thay real AI acceptance. 120 service AC + 24 system AC = 144 tiêu chí kế hoạch, không phải 144 test đã pass.