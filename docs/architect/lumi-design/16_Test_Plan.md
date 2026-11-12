# TEST PLAN — KẾ HOẠCH KIỂM THỬ VÀ NGHIỆM THU

**Mã:** LUMI-TP-001 · **Trạng thái:** Kế hoạch dự thảo; không thay thế CI results hoặc test evidence thật.

## 1. Mục đích

Xác minh chức năng, quyền, dữ liệu, hoạt động bất đồng bộ, hiệu năng và hành vi khi lỗi theo các FR/NFR thuộc release. Tách rõ **technical verification** (agent/CI có thể thực hiện) và **human acceptance** (product/operator/owner cần xác nhận).

## 2. Scope

- **P0 Core MVP:** Authentication, school/user management, homeroom/subject class, roster/assignment/enrollment/transfer/archive, Feed/Comments/Calendar, Notifications, audit/data-request intake/review, Web real integration.
- **P1 Document (sau review):** 5 formats, version SUCCESS fallback, grants, revoke, notes/bookmarks, crash/retry.
- **P2 Learning (sau review):** practice/official/assignment, immutable version, save/resume/auto-submit, approval/grade revision/appeal, late/resubmit.
- **P3 Intelligence (sau review):** provenance, duplicate/out-of-order, insufficient data, recommendation, aggregate privacy/export.
- **Ngoài phạm vi:** AI Service; không lập hay chạy QAS-06 RAG trong bộ test này.

## 3. Test levels và kỹ thuật

| Mức | Mục tiêu | Bằng chứng |
|---|---|---|
| Unit | Validation, state transition, service business rules | Unit report + revision |
| Contract | OpenAPI response/status/errors, event schema, boundary | Snapshot/consumer-provider contract |
| PostgreSQL integration | Transactions, locks, unique constraints, migrations, rollback | Test DB riêng + log redacted |
| Security negative | IDOR/cross-school/class, CSRF, token replay, lost permission | Deny + no data disclosure |
| Browser E2E | True role journeys, forms, toasts, retry, proxy, worker | Browser trace/screenshots with synthetic data |
| Fault injection | SMTP failure, worker crash/retry, DB down, race, timeouts | Result + invariant reconciliation |
| Performance | QAS-05 class-list/other available endpoints under TP-01 | CPU/RAM, latency, success, scope mismatch |
| Accessibility | Keyboard, focus, labels, responsive states | Checklist/browser/video/screen reader when available |
| Regression | Previously fixed defects and PR thread findings | Linked issue/test and CI result |

## 4. Test environments

- Core PostgreSQL 16 test DB, migration head; no SQLite substitution where DB concurrency matters.
- Next.js production **live** build and same-origin proxy against test Core; mock UI is separate UI-design test, not E2E evidence.
- Worker enabled for notification/delivery scenarios; synthetic email provider or approved testing inbox; no real student email/data.
- Browser Chrome baseline plus alternative browsers when resources available; record version/viewport/OS/timezone.
- Future services need approved DB/storage/worker test harness before running; not counted passed while absent.

## 5. TP-01 load configuration (đã định nghĩa trong Quality Attributes)

- 100 concurrent users; 10 classes, 50 students each; 20 documents per class, average file 10 MB; 30 questions/assessment; 10-minute stable load after warmup.
- Record CPU/RAM, DB, worker, network/region, service revision, response p95 by action, success rate and scope mismatch.
- Core class-list backend target p95 ≤500ms. Learning action targets: load practice ≤1000ms, save answer ≤1000ms, submit ≤2000ms; cached mastery read ≤1000ms; ≥99% valid requests succeed (targets, not current results).
- Prior class-list-only benchmark does not count as full TP-01, nor prove 358 CCU capacity.

## 6. Entry criteria

| Gate | Core MVP | Future service |
|---|---|---|
| Requirements | Rule/FR confirmed or documented open decision | Domain contract approved |
| Environment | Live Web/Core, Postgres migrated, worker ready | Dedicated storage/migration/service credentials |
| Data | Synthetic seed and role-specific accounts | Approved scenarios/files/grades/evidence |
| Code | Build/static checks, no critical compile errors | Service implementation + contract baseline |
| Secrets | No real PII or tokens in test artifacts | Storage/export security review |

## 7. Exit criteria

**Technical ready Core:** tests P0 passed, no known critical blocking defect, real browser E2E Admin→Lecturer→Student pass, school/class denial and 401/403/404/409/422 validated, worker/notification pass, code/docs/evidence revision traceable.

**Product acceptance:** operator/owner xác nhận scope, chính sách dữ liệu thật được duyệt, performance/backup/incident test phù hợp môi trường; không tự suy từ CI xanh.

**Future:** ADR/API/schema approved, positive/negative/edge/concurrency QAS evidence; không nghiệm thu bằng Mock.

## 8. Test data management

- Synthetic accounts: một Admin, một PRIMARY, một ASSISTING, học sinh ACTIVE/PENDING/LOCKED ở cùng trường, tối thiểu một trường thứ hai để kiểm tra IDOR.
- Academic year/semester, grade 6–12; AUTO và MANUAL classes; roster versions để tạo conflict.
- Social posts/comments/calendar; notification V2 event replay/V1 quarantine.
- Future docs: 5 types, valid/malformed, v1 SUCCESS/v2 FAILED, two classes/grants/revoke.
- Future Learning: saved answers, timeout, transfer, revision stale, grade correction and appeals.
- Future LI: duplicate/late/out-of-order version, insufficient/adequate evidence, small aggregate groups, export.
- Dữ liệu mỗi test cô lập; cleanup không được xóa DB thực ngoài phạm vi.

## 9. Defect classification và workflow

| Mức | Ví dụ | Xử lý |
|---|---|---|
| P0 Critical | Rò rỉ cross-school, Student tự duyệt điểm, token lộ, mất submission confirmed | Block release, fix + regression + security review |
| P1 High | Không login/activate, sai roster sau sync, notification gửi nhầm, grade conflict | Block affected workflow/release |
| P2 Medium | UI state sai nhưng backend vẫn an toàn, error copy chưa đúng | Fix theo kế hoạch, ghi rõ known issue |
| P3 Low | Visual polish, thông báo chưa tối ưu | Backlog; không dùng làm kết luận nghiệp vụ |

Issue: reproduction steps, expected/actual, scope/environment/source SHA, sanitized evidence, severity, owner, fix commit/test, retest status.

## 10. Test execution cycle

1. Review RTM và chọn release subset; xác nhận những rule chưa được quyết định.
2. Freeze image/source/migration/seed và xác nhận không mock.
3. Static/unit/contract; DB integration/negative; browser flows; fault injection; performance.
4. Lưu JUnit/coverage/logs/redacted screenshot/correlation IDs.
5. Triage finding, regression, rerun subset và CI full gate.
6. Sign-off technical verification; human acceptance riêng.

## 11. Test summary report form

| Trường | Nội dung cần điền |
|---|---|
| Release/SHA | Repo URL, commit, image digest, migration |
| Environment | OS/region/DB/runtime/browser/worker |
| Scope | Chức năng và QAS có kiểm tra |
| Results | Passed/Failed/Skipped/Not run **theo test** |
| Defects | Open P0/P1/P2 và linked issue |
| Evidence | Artifact links, timestamp, tool version |
| Limitations | AI excluded, future service unavailable, not full TP-01 |
| Decision | TECHNICAL PASS / PARTIAL / BLOCKED, human signoff |

## 12. Báo cáo kết quả lịch sử trong repository — không phải test mới

- `tasks/README.md` ghi PR #33: Core 360 PostgreSQL tests và Web 251 tests; PR #34: 368; PR #35: 380.
- Working-tree 30/10 có report 381 Core tests và migration 0014 trên PostgreSQL 16.15.
- `SYSTEM_DESIGN.md` 31/10 ghi PR #38 Core/Web CI passed. Trong bộ tài liệu này **chưa có thực thi test mới**; không coi các số này là kết quả kiểm thử của bản thiết kế.
- Benchmark 30/10 class-list subset: 58.521/58.521 HTTP 200, backend p95 21,84ms, client loopback p95 672ms, 0 scope mismatch; không full TP-01.