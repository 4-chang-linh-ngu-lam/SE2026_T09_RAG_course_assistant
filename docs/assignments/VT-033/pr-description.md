VT-033 allows operators to change only the Notification inbox default page size
through `NOTIFICATION_PAGE_SIZE_DEFAULT` (1..100,default20,process startup/restart).
Explicit query limits win. Shared pagination, recipient authorization, service,
repository, schema/migrations and application dependencies remain unchanged.

**DO NOT MERGE - pending team review. The120-actor load gate has NOT passed.**

Baseline: `9ee864c3404f8057b394592791404f6db8692826`.
RED commit: `6dd9ebfea7ae8617a04fb3ff5b570f93c23322bb`.
Correct implementation: `d9870162e79e93d01c873096cc886925ecda9665`.

Acceptance criteria: configurable default20/bounds1..100 and startup validation;
explicit-limit precedence; exact own-inbox items/order/cursor/unread/no-store;
current Identity/recipient isolation and unchanged read state on denial; no changes
to pagination of other endpoints. See the5AC,18cases and BVA in
`docs/assignments/VT-033/spec-and-plan.md` and `test-strategy.md`.

Local verification (Windows, dedicated PostgreSQL16.14 on127.0.0.1:15433):

- Initial Python3.12.0 baseline:397passed,4failed,1teardown error,0skipped, mostly
  Windows Unicode email/CLI decoding. Existing installed Python3.12.14+UTF8 fixed
  the4targeted cases; package versions were unchanged. Both results are preserved.
- RED on unchanged production: route expected limit2 but received20; real PG page
  expected2IDs but received20. Each exit1 on intended assertion; `01-red-*` logs.
- GREEN:69Notification tests passed; full Core439passed,0failed,0skipped. Ruff
  lint/format pass. Exact commands and JUnit are under `evidence/02-*`, `05-*`.
- Full app line91.39% (4604/5038), branch75.08% (916/1220). Notification router,
  service and repository line100%; repository branch7/8 (empty read-all branch
  missing). See coverage-summary.md; no threshold was changed.
- Local-only detached worktree mutation removed exactly one mark-read recipient
  predicate.3security cases passed before,3failed on persisted foreign read_at,
 3passed after exact-byte restoration. Main source unchanged; worktree removed;
  no mutated production source was committed/pushed. Evidence03-04 includes diff
  and matching original/restored hashes.
- Flaky:38new cases passed in reversed file order;4ownership/cursor/read-all
  concurrency cases repeated3times all pass. Finite experiments, fresh test DBs.

Real loopback HTTP/Identity/PostgreSQL load,120actual actors/peak in-flight,
30swarmup+180smeasurement,zero think time,2items/page,5synthetic notifications/user:

| Client / pool | Requests | p95 client | Errors | Gate |
|---|---:|---:|---:|---|
|HTTPX0.28.1 /5+10|3541|17578.75ms|0|FAIL latency|
|HTTPX2 2.16.0 /5+10|7016|3472.58ms|524HTTP503+2transport|FAIL errors|
|HTTPX2 2.16.0 /15+0|7310|3360.44ms|246HTTP503+2transport|FAIL errors|

No content/ownership mismatch observed among200responses. Percentiles include all
statuses. Pool15+0 is an existing Core tests README profile with the same15maximum
connections/admission14; production defaults/3500ms target/workload were unchanged.
All raw failed runs are retained, not relabeled. Shared12-logical-CPU/16GB Windows
workstation, Docker/WSL, client/server same process and zero-think closed-loop load
limit interpretation. See `load-analysis.md`; no production capacity claim.

Reproduce from services/core after setting dedicated TEST_DATABASE_URL/DATABASE_URL
and PYTHONUTF8=1 (full CMD/PowerShell setup in assignment README):

```text
.venv\Scripts\python.exe -m pytest tests/notification -q -W error -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider --cov=app --cov-branch
.venv\Scripts\python.exe ../../docs/assignments/VT-033/verify_mutation.py
.venv\Scripts\python.exe tests/performance/vt033_notification_load.py --client-library httpx2 --users 120 --page-size 2 --warmup-seconds 30 --duration-seconds 180 --output local-load.json
```

The sustained runner exits1 while this gate fails. Set pool15+0 as documented in
README to reproduce the final measurement profile.

Changed production:common/config.py and notification/router.py only. Added2test
files, standalone load runner, local-only mutation/evidence tools, contract/README
and assignment evidence/report sources. No frontend or other-service implementation.

Owner notification/review requested: **TV4 Notification and Common/Identity
consumers** for shared Settings, config deployment/restart and API documentation.
Student must read/review the report/reflection/responsibility statement. No human
approval is asserted. Codex/AI assistance and the separate user-requested read-only
plan reviewer are disclosed in `ai-usage.md`; full prompt and318-word reflection
are saved. PDF will be added after real branch/PR/CI URLs are verified.

GitHub Actions is independent evidence after push, not a substitute for local RED.
The workflow's optional class-list load job does not verify this Notification NFR.
