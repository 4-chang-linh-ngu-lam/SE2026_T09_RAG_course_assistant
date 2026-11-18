# AC / risk → executed test → commit → evidence

Baseline `9ee864c3404f8057b394592791404f6db8692826`.
RED tests `6dd9ebfea7ae8617a04fb3ff5b570f93c23322bb`.
Correct implementation `d9870162e79e93d01c873096cc886925ecda9665`.
Actual PR/CI/head URLs and full/coverage/load values are in `submission.json`.

Paths C and P below mean `services/core/tests/notification/test_vt033_config.py`
and `services/core/tests/notification/test_vt033_postgres.py` respectively.

| AC / risk | Test IDs | Actual function(s) | Commit / observed evidence |
|---|---|---|---|
|AC1 / R3 invalid settings or wrong default|T01-T05,T09,T16|C::test_settings_default,test_settings_boundaries,test_invalid_env_prevents_startup,test_route_resolves_default; P::test_configured_inbox_business_outcome,test_baseline_default_and_empty_inbox|RED6dd9ebf route expected2/actual20; PG expected2/actual20. Correct patchd987016:69 Notification tests passed,0failed,0skipped;01-red-*,02-green-notification*|
|AC2 / R1 query overrides and cursor validation|T06-T07,T10-T11,T17|C::test_explicit_limit_overrides_default,test_invalid_query_never_calls_service; P::test_explicit_limit_business_outcome,test_foreign_cursor_does_not_change_state|d987016; BVA0,1,2,99,100,101; errors cause no service call/write; PG IDs/state checked;02-green-notification-junit.xml|
|AC3 / R1,R4 business envelope/order/count/rollback|T09-T10,T15-T16|P::test_configured_inbox_business_outcome,test_explicit_limit_business_outcome,test_list_failure_rolls_back_and_recovers,test_baseline_default_and_empty_inbox; helper check_page|d987016; exact ID/payload/read/created_at/order/cursor/unread and no-store; actual SQL division-by-zero failure returns safe500, next list succeeds with unchanged data|
|AC4 / R1,R4 recipient/current status|T11-T14|P::test_cross_recipient_mark_read_preserves_business_state,test_foreign_cursor_does_not_change_state,test_own_read_and_read_all_preserve_other_inbox,test_locked_user_cannot_read_inbox|d987016;03-before3pass→03-killed3fail on persisted read_at→04-restored3pass; guard restored exact hash; other user's read_at unchanged on correct code|
|AC5 / R2 shared pagination regression|T08 and entire original Core suite|C::test_other_endpoint_keeps_twenty; original Identity OpenAPI snapshot, Classroom/Social/Admin and other Core tests|d987016; shared pagination/service/repository byte content unchanged;02-green-notification* and full JUnit/coverage artifacts|
|NFR / R5 real120 client concurrency and truthful latency|T18|services/core/tests/performance/vt033_notification_load.py::exercise,main|Harness/source hashes and patch SHA recorded in07-load.json; actual tasks/peak in-flight, client p50/p95/p99/max, status and content errors; finite local scope only|

All18 cases with preconditions/input/business outcome/level/priority/file are in
`test-strategy.md`. Full-suite JUnit is `evidence/02-green-full-junit.xml`; coverage
XML/JSON and missing branch analysis are `05-coverage.*` and `coverage-summary.md`.
Flaky experiment commands/counts are `06-flaky-*`. No skipped DB test is counted
as passed. Initial baseline Windows failures and repaired-environment reruns are
retained separately; they are not the feature's RED evidence.
