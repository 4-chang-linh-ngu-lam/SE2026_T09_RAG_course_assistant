# BT3 — Bùi Văn Khởi / 23001893 / VT-034

Individual branch, **not merged**, awaiting TV3 (Social/Web) and TV4 (Notification)
review. [Branch](https://github.com/4-chang-linh-ngu-lam/SE2026_T09_RAG_course_assistant/tree/bt3/23001893-vt034-notification).
The branch adds in-app notifications when an authorized author changes a post.
See [PLAN](PLAN.md) for specification, reviewed assumptions and two weak AI tests
replaced before execution. No migration, new service, SMTP or public HTTP schema.

## Commits and evidence

| Phase | GitHub commit | Evidence |
|---|---|---|
| Baseline | `9ee864c3404f8057b394592791404f6db8692826` | Original group repository |
| Spec/plan | `b735a4d0cb4dcbad21b33a69ace1ddc7dd73ca97` | PLAN.md before code |
| Red tests | `f044b8f6681879c1810d97805d731a4513807a8d` | evidence/red.log: 9 failed, 8 passed |
| Patch | `35171c1efb27b8207ade8b9e4bc6677d66ad2b63` | evidence/green.log: 117 passed; load separate |

Commits were published with the connected GitHub API after CLI push lacked
credentials. Local execution commits are mapped in evidence/execution.json;
publication changes commit metadata, not the tested source content. Source blob
hashes are recorded so the mapping is independently checkable.

## Run (Python 3.12, PostgreSQL 16+, Node 22+)

Use only a disposable local PostgreSQL server/account with CREATEDB. Fixtures make
a fresh `notification_test_<uuid>` database for each test and drop only that DB.
Do not set TEST_DATABASE_URL to a server with data you need to preserve.

```bash
cd services/core
python -m pip install -e '.[dev]'
export TEST_DATABASE_URL='postgresql+psycopg://USER:PASS@127.0.0.1:5432/postgres'
export PYTHONPATH=.
python -m pytest tests/social tests/notification tests/vt034 --ignore=tests/vt034/test_load.py -q --cov=app.modules.social.feed.service --cov=app.modules.notification.events --cov=app.modules.notification.worker --cov-branch --cov-report=term-missing
python -m pytest tests/vt034/test_load.py -q
python tests/vt034/mutation_check.py
```

PowerShell: replace `export NAME=...` with `$env:NAME='...'`.
Without TEST_DATABASE_URL, PostgreSQL tests skip; skipped tests are NOT evidence.
For Linux without an installed PostgreSQL server, an optional isolated launcher is
included (`python -m pip install pgserver==0.1.4`; then
`python tests/vt034/local_postgres.py python -m pytest tests/vt034 -q`). It initializes
an ephemeral UTF-8 cluster, disables Unix sockets, binds TCP loopback and cleans up.

```bash
cd apps/web
npm ci
npm run check
NEXT_PUBLIC_DATA_MODE=live npm run build
```

This workspace blocks the tsx CLI Unix IPC socket; equivalent executed test command:
`node --import tsx --test --test-concurrency=2 --test-timeout=10000 tests/*.test.ts`.
Boundary checks and tsc passed before that environmental CLI failure; the alternate
runner passed 260 tests. Live build and release checks also passed.

## Pairwise, mutation, load and limits

- Four factors: length 1/10000/10001; author/other-member/outsider; ACTIVE/ARCHIVED;
  delivery ok/fail. Deterministic covering array has **9 rows** covering **37 pairs**
  drawn from 36 Cartesian combinations. Independent audit enumerates every value pair.
  Delivery is masked for rejected requests; TC07/TC10 directly cover successful
  max-size edits with healthy/failing delivery, rather than claiming pairwise alone
  proves those combinations.
- TC06 tests exact batch size 1000. mutation_check creates a temporary detached
  commit with `> 1000` changed to `>= 1000`; its failure must be TC06[1000], not an
  import/environment error. Original working tree bytes must stay unchanged.
- Load: Uvicorn/TCP HTTP/JWT, PostgreSQL 16.2, 60 simultaneous tasks per wave,
  three waves / 180 updates, 10000 Unicode characters; 60 distinct posts, one
  author/class. Admission capacity 14, DB pool 5+10; worker stopped. Raw timings,
  nearest-rank p95, errors and durable counts are in evidence/load.json.
- Body validation does not cap raw HTTP bytes before parsing; ingress size limits
  and very large recipient fanout remain outside this patch.
- This proves a finite local scenario, not 60 independent logins, sustained
  production SLO, large-class fanout, browser accessibility or notification latency.
- Repeated retry/concurrency tests run in reverse order with fresh fixture DBs;
  backoff readiness is controlled with DB time, not sleep. Random UUIDs label
  isolated data and are never used as timing/order oracles.

## Traceability

| AC / risk | Test case and file (`services/core/tests/vt034/`) | Commit | Result |
|---|---|---|---|
| AC1 event + no-op | TC07/08 test_postgres.py | patch above | Pass |
| AC2 atomic enqueue, failed delivery/retry/dedup | TC09/10/15 test_postgres.py | patch above | Pass |
| AC3 authorization/current scope | TC11/12/13 test_postgres.py; existing Social/Notification tests | patch above | Pass |
| AC4 body bounds + privacy | TC02/03 test_contract.py, TC07/10/12 test_postgres.py | patch above | Pass |
| AC5 bounded worker batch | TC05/06 test_contract.py | patch above; temporary mutant in mutation.json | Pass; mutant killed |
| Large-input timeout/p95 | TC14 test_load.py | patch above | Local result in load.json |
| UI notification copy/link | apps/web/tests/vt034-notification.test.ts | patch above | Pass |

No group review or production acceptance has been claimed. Student should inspect
the diff, pairwise choices, every oracle and PDF reflection before submitting.
