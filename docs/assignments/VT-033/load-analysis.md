# Local load result: FAIL (three measured profiles)

All three runs used120 distinct actors, real loopback Uvicorn/Identity/PostgreSQL16,30s warmup+180s closed-loop zero-think-time measurement, page default2 and the same application hash. No test suite/build ran during each sustained measurement. Background Docker/WSL/workstation activity was not isolated.

|Profile|Raw report|Actual tasks / peak in-flight|Requests|Client p95 ms (all statuses)|Errors|Statuses|Verdict|
|---|---|---|---|---|---|---|---|
|HTTPX0.28.1 / pool5+10|07-load-httpx.json|120/120|3541|17578.749|0|{'200': 3541}|FAIL|
|HTTPX2 / pool5+10|07-load-httpx2-default-pool.json|120/120|7016|3472.581|526|{'200': 6490, 'transport_error': 2, '503': 524}|FAIL|
|HTTPX2 / pool15+0|07-load.json|120/120|7310|3360.441|248|{'200': 7062, 'transport_error': 2, '503': 246}|FAIL|

**No profile passed the complete gate.** In the last profile p95<=3500ms, but errors remained; do not label this120-user operational acceptance. Percentiles include unsuccessful requests, not only successful200s. Every200 was checked against actor-specific IDs,payloads,read flags,cursor,unread count and no-store. No content/ownership mismatch was observed in this finite sample.

The much lower ASGI backend latency than legacy client latency indicates substantial waiting outside measured ASGI processing; this does not identify a single root cause. Switching to already-declared HTTPX2 changed client behavior and increased throughput;524503+2transport errors in the default-pool run exposed admission/transport limits. Pool15+0 reused more connections under the same15-connection maximum/admission14 and reduced errors, but did not eliminate them. These are observations/inferences, not proof that PostgreSQL, the client library or a particular code path alone caused the failures.

Pool tuning follows services/core/tests/README.md:67-68. Production defaults, source,authorization,actors,measurement duration and3500ms target were not changed. This feature-sized patch does not attempt unrelated Core admission/performance redesign. Highest-value next investigation: isolate client and server processes/CPU, collect connection/admission timing and memory telemetry, then repeat fixed workload with a documented arrival/think model and mixed read/write/delivery operations. External network/browser/multi-worker/production capacity remains unverified.

Archived outputs:07-load-run.json/.log historically wrote07-load.json, preserved unchanged as07-load-httpx.json before the next profile.07-load-httpx2-run.* historically wrote the same path, archived as07-load-httpx2-default-pool.json.07-load-pool15-run.* belongs to final07-load.json. See07-load-index.json for current paths/source hashes. Smoke outputs are execution checks, not acceptance.
