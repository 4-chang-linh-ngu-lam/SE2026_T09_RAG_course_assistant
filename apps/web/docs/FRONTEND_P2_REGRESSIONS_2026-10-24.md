# Frontend P2 follow-up — 24/10/2026

Base: `381fa1ca61105045408d3484941f89773bd47aab` on `fix/12-core-full-main-conflicts`.
Worker: Codex for state/integration/tests; no UI worker or new dependencies.

## Changes

| Finding / route | Resulting behavior |
|---|---|
| Profile save overwrote edits made while awaiting ACK (`/account`) | Each user edit increments a draft revision. A save response normalizes the submitted name and reports success only if that revision is still current. A newer draft remains editable/dirty and requires its own explicit save. |
| Unknown login stayed locked after confirmed sign-out (`/login`) | Explicit session checking waits for the current provider status. Only `signed-out` with no session error clears the unknown flag. Loading/unavailable/authenticated states do not unlock a second login. The check button is disabled while checking; credentials are not replayed automatically. |
| Multi-day calendar missing in following month/day (class and global calendar) | Month/list and both day grids test timestamp interval overlap. Local next-day boundaries respect DST. End is exclusive, matching Core's existing `ends_at > from` and `starts_at < to` filters. Point deadlines occupy their start day. Week selection keeps the clicked day and clamps a prior-month event start to the displayed month. |

No backend API/schema/permission changes. Session provider, credential transport,
adapter boundaries and live/mock isolation remain unchanged. `calendar.ts` is
owned by Web's calendar presentation; all eight interval tests use synthetic
events and explicitly restore the process timezone.

## Verification

- Before changes: `npm.cmd run check` passed 346 tests, boundaries and TypeScript.
- After changes: `npm.cmd run check` passed 354 tests, including eight regressions
  for 31 October–2 November, an event spanning a whole month, midnight exclusion,
  year rollover/leap day, point deadlines, differing timezone/date labels,
  23/25-hour DST days and legacy/invalid intervals.
- `npm.cmd run typecheck` passed after connecting the browser regression module.
- `npm.cmd run test:core` with the existing Chrome binary: passed ten browser
  groups (including all three P2 cases), 22 HTTP groups, production live build,
  fixture-canary release scan, non-root runtime, migration check, repeat-safe seed
  and DB outage/recovery. Browser summary reports zero uncaught exceptions at
  desktop/mobile viewports 1440/390. Fixture cleanup completed successfully.

The existing `npm.cmd run test:core` browser extension now requires ten Core
browser groups, including three P2 regressions in `core-p2-browser-regressions.ts`:

1. Hold the actual profile PATCH, type B while A is pending, release A, ensure B
   survives without a false success, explicitly save B and reload to verify it.
2. Lose a login request offline, keep submit locked after unavailable session
   checking, restore connectivity, confirm signed-out and retry in the same form.
3. Supply synthetic calendar GET receipts while auth/class reads remain live;
   verify a month-boundary event in both day cells, the next month's list and the
   selected week, excluding an event ending exactly at midnight. This is a UI
   regression with controlled calendar data; the earlier browser group still
   checks real calendar create/edit persistence.

The browser runner uses the existing headless Chrome binary and isolated
PostgreSQL/SMTP TLS fixtures. No real Gmail, operational accounts or DB are used.
The first attempt stopped before fixture startup because Docker Desktop was off;
that attempt is not counted as a passing test.

Review scope: Web.Identity, Web.Social/Calendar and shared draft/session consumers.
The old dated acceptance reports remain historical snapshots, including their
previous browser group counts. This follow-up does not certify other services,
production load or every possible UI state.
