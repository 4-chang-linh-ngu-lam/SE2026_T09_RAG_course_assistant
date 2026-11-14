# BT3 - Mai Huy Hoàng / 23001878 / VT-033

Repo local: `D:\app\cnpm\W3\SE2026_T09_RAG_course_assistant`.
Baseline `9ee864c3404f8057b394592791404f6db8692826`; branch
`assignment/23001878-vt033-notification-config`. No pull/rebase changed the baseline.

Read [spec/plan](spec-and-plan.md), [independent AI review](plan-review.md),
[18 risk-based cases](test-strategy.md), [traceability](traceability.md),
[AI usage](ai-usage.md), [coverage](coverage-summary.md), [reflection](reflection.md)
and the machine-readable [submission summary](submission.json) for actual results.
Human/student/module-owner approval is pending. Do not merge the Draft PR.

## Feature and important lines

`NOTIFICATION_PAGE_SIZE_DEFAULT`: integer1..100, default20, loaded and validated by
existing Settings at process initialization. Restart after an environment change.
An omitted Notification limit uses that loaded field. Explicit limit1..100 wins;
invalid query values do not become fallbacks. Existing cursor decoding is reused.
Other endpoints continue using unchanged `get_pagination` (default20).

Production changes are only `app/common/config.py` (one bounded Field) and
`app/modules/notification/router.py` (Query/Settings imports, local dependency and
route binding). `limit is None` matters: it selects configuration only for omission;
FastAPI rejects invalid supplied values. Service, repository, identity checks,
schema/migrations and dependencies are unchanged. API Contract/Core README document
the setting. Notification/TV4 and Common/Identity owner review is requested in PR.

## Windows setup and dedicated PostgreSQL

Actual execution shell: Windows PowerShell5.1. Python3.12.0 baseline reproduced
Windows Unicode/CLI failures (397 passed,4 failed,1 teardown error); Notification
baseline still passed. Final verification uses **already installed CPython3.12.14**
and UTF-8 mode, with unchanged package versions. The initial failed results remain
in `00-baseline-full.*`; recovery is recorded in `02-environment-recovery.json`.
The project requires Python>=3.12; do not change its dependency file.

CMD, from root (use a current Python3.12 patch interpreter):

```bat
cd /d D:\app\cnpm\W3\SE2026_T09_RAG_course_assistant\services\core
py -3.12 --version
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
```

On this machine `py -3.12` selects3.12.0. The recorded environment correction reused
the already installed3.12.14 interpreter, without upgrading the package set:

```powershell
& 'D:/app/GPT_3DSMAX/.tools/python/cpython-3.12.14-windows-x86_64-none/python.exe' -m venv --upgrade --without-pip .venv
```

Start Docker Desktop and inspect containers/port before creating anything:

```powershell
docker ps -a --format '{{.Names}} {{.Image}} {{.Status}} {{.Ports}}'
Get-NetTCPConnection -LocalPort 15433 -ErrorAction SilentlyContinue
```

This run created a new `vt033-pg`, image `postgres:16-alpine`, bound only to
`127.0.0.1:15433`; generated credential is in ignored `.venv/vt033-local.json`.
Never print/commit that file or point tests at production/team databases. Container
has no preexisting user volume; existing containers/volumes were not removed.
Starting Docker Desktop may auto-start unrelated containers according to their
existing policies; shared-machine activity is disclosed by the load report.

If reproducing on a fresh machine, generate a local password in memory, create a
new dedicated container and store its DSN only in the ignored venv (PowerShell,
from services/core, after confirming that the name and port are free):

```powershell
$localPassword = [guid]::NewGuid().ToString('N') + [guid]::NewGuid().ToString('N')
docker run -d --name vt033-pg --label assignment=VT-033 -e POSTGRES_USER=vt033 -e "POSTGRES_PASSWORD=$localPassword" -e POSTGRES_DB=vt033 -p 127.0.0.1:15433:5432 postgres:16-alpine
@{url=('postgresql+psycopg://vt033:'+$localPassword+'@127.0.0.1:15433/vt033');container='vt033-pg'} | ConvertTo-Json | Set-Content -Encoding utf8 .venv/vt033-local.json
docker exec vt033-pg pg_isready -U vt033 -d vt033
```

If that container already exists, inspect it and its labels/port before using it;
do not replace/delete it. Wait for `pg_isready` to report accepting connections.

PowerShell environment for each test terminal:

```powershell
$localConfig = Get-Content -Raw .venv/vt033-local.json | ConvertFrom-Json
$env:TEST_DATABASE_URL = $localConfig.url
$env:DATABASE_URL = $localConfig.url
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
```

CMD equivalent (replace the placeholder with the local-only credential, never
commit the resulting command/environment):

```bat
set "TEST_DATABASE_URL=postgresql+psycopg://vt033:<LOCAL_TEST_PASSWORD>@127.0.0.1:15433/vt033"
set "DATABASE_URL=%TEST_DATABASE_URL%"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
```

The account must have CREATEDB. Notification fixtures create/drop generated sibling
databases. The full older Core suite also mutates the specified base test database;
it must be disposable. Migrate **only** the new VT033 test database:

```bat
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check
```

## Tests, evidence and test-first reproduction

From services/core with the test environment set:

```bat
.venv\Scripts\python.exe -m ruff check app tests migrations
.venv\Scripts\python.exe -m ruff format --check app tests migrations
.venv\Scripts\python.exe -m pytest tests/notification -q -W error -p no:cacheprovider
.venv\Scripts\python.exe -m pytest -q -W error -p no:cacheprovider --cov=app --cov-branch --cov-report=term-missing --cov-report=xml:../../docs/assignments/VT-033/evidence/05-coverage.xml --cov-report=json:../../docs/assignments/VT-033/evidence/05-coverage.json --junitxml=../../docs/assignments/VT-033/evidence/02-green-full-junit.xml
```

The recorded RED commit is `6dd9ebfea7ae8617a04fb3ff5b570f93c23322bb`; correct patch
commit is `d9870162e79e93d01c873096cc886925ecda9665`. Production application hash
matched baseline during both RED runs; exact commands/exit1 are in `01-red-*.json`.
To reproduce RED without modifying your working branch, use a detached worktree at
the RED commit and the absolute path to the existing venv Python; run:

```bat
python.exe -m pytest "tests/notification/test_vt033_config.py::test_route_resolves_default[2]" -q -W error -p no:cacheprovider
python.exe -m pytest "tests/notification/test_vt033_postgres.py::test_configured_inbox_business_outcome[2]" -q -W error -p no:cacheprovider --tb=short
```

Here `python.exe` means the full existing venv executable path, and cwd is that
worktree's services/core. Expected failure:2 vs20, not unavailable DB/import errors.
Do not switch/reset a dirty working tree. Do not count skips as database verification.

`record_check.py LABEL -- COMMAND ...` records timestamp/SHA/application hash,
command/exit and credential-redacted output. Commands must not contain credentials.
Whitespace in logs/XML is normalized for `git diff --check`; outcomes are retained.

## Local-only mutation and flaky experiments

After the correct production code is committed:

```bat
.venv\Scripts\python.exe ../../docs/assignments/VT-033/verify_mutation.py
```

Runner creates a detached worktree under ignored venv, passes3 security cases,
removes exactly one mark-read recipient predicate, expects3 business-state failures,
restores exact original bytes in `finally`, passes3 again, verifies hashes/main
source and removes only its clean generated worktree. It never commits/pushes the
mutant. Inspect `03-mutation.diff/.json`, `03-before.log`, `03-killed.log` and
`04-restored.log` before push. A surviving/environment-failed mutant is not a kill.

Flaky commands/results are in `06-flaky-*.json/.log`: normal/reversed file order,
fresh DB per test, repeated ownership/cursor/read scenarios and the existing
Event-synchronized read-all/delivery concurrency scenario. Finite repetitions are
not proof of zero flakes. No pytest-randomly/repeat dependency was added.

## Real HTTP load

```bat
.venv\Scripts\python.exe tests/performance/vt033_notification_load.py --users 120 --page-size 2 --warmup-seconds 2 --duration-seconds 3 --output ../../docs/assignments/VT-033/evidence/07-smoke.json
.venv\Scripts\python.exe tests/performance/vt033_notification_load.py --users 120 --page-size 2 --warmup-seconds 30 --duration-seconds 180 --output ../../docs/assignments/VT-033/evidence/07-load-httpx.json
.venv\Scripts\python.exe tests/performance/vt033_notification_load.py --client-library httpx2 --users 120 --page-size 2 --warmup-seconds 30 --duration-seconds 180 --output ../../docs/assignments/VT-033/evidence/07-load-httpx2-default-pool.json
set "DATABASE_POOL_SIZE=15"
set "DATABASE_MAX_OVERFLOW=0"
.venv\Scripts\python.exe tests/performance/vt033_notification_load.py --client-library httpx2 --users 120 --page-size 2 --warmup-seconds 30 --duration-seconds 180 --output ../../docs/assignments/VT-033/evidence/07-load.json
```

Smoke always has `passed_vt033:false`/exit1 because it intentionally does not meet
the minimum sustained measurement profile. It only validates harness execution.
Full run gates120 actual tasks/peak in-flight, >=30s warmup,>=180s measurement,
client p95<=3500ms, zero HTTP/transport/timeout/content/ownership errors. Defaults
use the application's pool5+10/admission14, not120 simultaneous SQL executions.
No auth/service override or external AI service is used. Report includes client
and server percentiles, machine/DB/pool metadata, run ID/SHA/source hashes, statuses
and shared-workstation limitations. Do not run full tests/builds during the timed
measurement. The existing class-list harness remains unchanged.

The initial full HTTPX0.28.1 profile recorded3541 requests,0HTTP/content errors,
p95 client17578.75ms (FAIL) despite much lower backend latency. Its raw report is
archived as `07-load-httpx.json`; `07-load-run.json/.log` retain the historical
command, which originally wrote `07-load.json` before archiving. The later run uses
HTTPX2 2.16.0 already present in `.[dev]`, with identical app/DB/pool/actor/duration
and target. `--client-library` explicitly records this measurement choice. Neither
profile proves browser/network/production capacity; report both, including FAIL.

HTTPX2 with default pool5+10 recorded7016requests,6490HTTP200,524HTTP503 and2transport
errors (p95 client3472.58ms): **FAIL**, despite p95 alone being below3500ms. It is
archived as `07-load-httpx2-default-pool.json`; historical metadata/log are
`07-load-httpx2-run.*`. The final profile uses pool15+0 (15retained,0overflow),
already recommended by `services/core/tests/README.md`, still maximum15 connections
and admission14. This changes only the test process environment, not app defaults.
PowerShell equivalents for that profile are `$env:DATABASE_POOL_SIZE='15'` and
`$env:DATABASE_MAX_OVERFLOW='0'`. Read `07-load.json` for its actual verdict; do not
infer PASS from p95 if errors are present. All three raw reports are retained.

## PDF and delivery

GitHub branch, Draft PR, CI run and verified state live in `submission.json` and
`evidence/08-github.json`. CLI portable is tool-only, under ignored venv. Git
Credential Manager supplies its token in process memory; tokens are never logged.
No merge/force-push/main mutation is authorized.

Report tools are isolated in `.venv/reporting-deps`, outside application imports:

```bat
py -3.12 -m pip install --target services/core/.venv/reporting-deps reportlab
py -3.12 docs/assignments/VT-033/render_report.py
```

These two commands run from repo root. PyMuPDF/pypdf already installed on the host
are used to render/check all pages, embedded Vietnamese font, clickable links and
page count. Final PDF is root `BT3_23001878_VT-033.pdf`; main8 pages plus appendices.
See `evidence/09-pdf-qa.json` for the actual page/text/link/font checks. The student
must review the final report and responsibility statement before Classroom submission.
