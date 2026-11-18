# Coverage and risk coverage

Actual full local run:439 passed,0failed,0skipped, Python3.12.14/PostgreSQL16.14.

Full app line coverage: **91.39% (4604/5038)**.
Branch coverage: **75.08% (916/1220)**.
The combined line+branch percentage printed by pytest-cov is a different metric.

|Notification file|Lines covered/total|Branches covered/total|Missing lines|Missing branches (from,to)|
|---|---|---|---|---|
|app/modules/notification/__init__.py|0/0|0/0|[]|[]|
|app/modules/notification/events.py|81/83|24/26|[101, 114]|[[99, 101], [113, 114]]|
|app/modules/notification/models.py|17/17|0/0|[]|[]|
|app/modules/notification/public.py|10/10|2/2|[]|[]|
|app/modules/notification/repository.py|34/34|7/8|[]|[[73, -69]]|
|app/modules/notification/router.py|31/31|0/0|[]|[]|
|app/modules/notification/schemas.py|16/16|0/0|[]|[]|
|app/modules/notification/service.py|25/25|0/0|[]|[]|
|app/modules/notification/worker.py|46/66|8/20|[75, 89, 90, 91, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 114]|[[28, 92], [74, 75], [83, 28], [101, 102], [101, 103], [104, 105], [104, 106], [106, -95], [106, 107], [108, 109], [108, 110], [113, 114]]|

Repository missing branch73?exit is the no-watermark (empty inbox) read-all path. It is outside the new default-selection behavior and is disclosed rather than inferred covered from line coverage. Router reports no counted branches because its conditional expression is on one line; both omitted and explicit outcomes are nevertheless asserted in tests.

Risk coverage:AC1/R3 settings+startup+BVA;AC2/R1 query/cursor;AC3/R1/R4 exact business envelope and SQL-failure recovery;AC4/R1/R4 current status/recipient/persisted state+mutation;AC5/R2 other-endpoint default and full regression. All5AC have finite executed evidence, not proof of universal correctness. T18 load evidence is separate from pytest coverage.

Other unexecuted paths include Identity delivery-worker process entry, Notification worker CLI/retry scheduling-error paths, and permission/error variants outside this slice. Exact missing branches for all files are in evidence/05-coverage.json and term-missing log. Subprocess/long-running worker coverage is not automatically combined into the parent report; do not equate0% in a worker module with a feature regression or certify those paths from other tests.

No coverage threshold was changed. Selected authorization mutation was killed; this is one targeted mutation, not an exhaustive mutation score. Browser journeys, mixed read/write/delivery load, multiple workers, external services and production capacity remain outside this finite run.
