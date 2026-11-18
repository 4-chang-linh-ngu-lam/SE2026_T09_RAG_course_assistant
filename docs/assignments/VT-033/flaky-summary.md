# Flaky experiments

F1: normal order covered by full439-pass run (38 new cases), reversed file order38passed. F2: ownership/cursor/read/read-all-delivery synchronization group repeated3times,4passed per round (12passes). No failures/skips observed; finite shared-machine experiments, not proof of no flakes.

Exact commands,timestamps,source SHA and exits are in evidence/06-flaky-*.json. Each PG test uses a fresh generated sibling DB. Settings/overrides are fixture-restored; concurrency uses Events and explicit sequencing. The reversed-order run overlapped the last portion of full-suite correctness testing on separate sibling databases; the timed load runs did not overlap test/build jobs.
