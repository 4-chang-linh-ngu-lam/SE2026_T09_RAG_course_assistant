# Web–Core connection fixes — 23 October 2026

The user's current priority is functional frontend/backend integration. Performance optimization and the Core load target are deferred; the earlier [runtime report](CORE_RUNTIME_FOLLOWUP_2026-10-23.md) remains historical evidence for that separate work.

## Changes

| Problem | Result |
|---|---|
| Live Student/Teacher home and class overview returned unavailable although scoped class reads already existed | Home uses the existing class-list view; overview reads the current class and opens live feed/calendar. Other-service material, grading and personal-history summaries remain explicitly unavailable. |
| Archived class cards opened uncontracted history/grading workspaces | Live cards open the available Core overview. Preview behavior is retained. |
| Valid uppercase UUID links disagreed with lowercase response IDs | Route/resource keys and Social guards use UUID identity. Opaque filters/cursors and non-UUID preview IDs retain their original meaning. Duplicate pagination rows differing only in UUID case are rejected. |
| Notification read acknowledgement could reject the requested UUID solely because of letter case | Read receipts compare canonical UUID identity; case-variant duplicate inbox rows are rejected. |
| A post-write 401/403/404 erased the confirmed management acknowledgement | Resource data is cleared on lost access, while the minimal confirmed operation receipt and reload barrier remain. |
| Failed permission checks during unknown-outcome reconciliation cleared the uncertainty | The write stays blocked until a successful fresh read and explicit reviewed acknowledgement. No mutation is automatically replayed. |
| Definite 422 validation rejection required an unrelated full reload before correcting the form | Rejected validation can be corrected and submitted; stale/conflicting/uncertain state still requires reconciliation. |
| Calendar markup used different class names from the existing stylesheet, rendering the month as one long column | Calendar uses the existing seven-column grid, weekday/header/detail styles and bounded grid tracks. Real browser geometry checks verify seven days per row. |
| A successful reconciliation left the old network error visible | Feed/calendar clear the previous error when fresh server data loads, retaining the user's unsent text. |

The browser proxy remains the same approved **63 operations**. No endpoint, backend DTO, business rule, database migration, permission policy or external service was added. `WorkspaceData.coreClassroom` is a local view-model availability marker, not a wire field. Changes are owned by Web data adapters, routing and controller integration; review owners are Web, Core.Classroom and Core.Notification for the affected consumer behavior. Codex performed these logic/wiring repairs and acceptance; no source was sent to AGY in this follow-up.

## Verification

Machine-readable record: [connection evidence](evidence/core-web-connection-2026-10-23.json).

- `npm.cmd run check`: **324 passed**, zero failures/skips; includes boundaries and TypeScript.
- `CORE_BROWSER_EXECUTABLE='C:\Program Files\Google\Chrome\Application\chrome.exe'` with `npm.cmd run test:core`: **exit 0** after the approved kernel/RTC reset. The normal runner rebuilt the latest production live Core/Web images; build, TypeScript and release fixture scan passed. Private artifact directory: `lumi-core-smoke-SfJ73F` under the Windows temporary directory.
- **22 HTTP groups passed**: seven groups cover the 46 approved Classroom/Social/Administration operations, seven cover Notifications, and eight cover Identity/security. The runner also verified the non-root installed Core package, migration check, repeat-safe synthetic seed, TLS SMTP fixture and DB outage/recovery (`ready 503`, `live 200`, then `ready 200`). External SMTP was not tested.
- **Five real Chrome groups passed**, at 1440/390 px with zero uncaught JS exceptions: Admin save/reload persistence; Student live home/overview, uppercase UUID, feed/comment edits and HttpOnly session restore; offline unknown-outcome handling without replay, explicit read reconciliation and forbidden route; Teacher calendar create/edit/reload; and Admin lock revoking an open Student session. The latest calendar seven-column geometry and cleared reconciliation-error assertions passed. Mobile feed and desktop calendar screenshots were inspected. This certifies those journeys, not every product route or future sleep/restart cycle.
- Earlier acceptance failures and synthetic-only JWT diagnostic runs established the clock fault described below. They are historical diagnosis, separate from the successful final normal acceptance run; the additional 600 established-session reads are not added to the HTTP group count.
- `git diff --check`: passed.
- Main development runtime: Web login 3000=200, Core ready 8000=200, anonymous proxied Admin read=401. Test containers/volumes, browser profiles and generated credential/mail files were verified removed. Existing development data was preserved.

The browser runner is optional through `CORE_BROWSER_EXECUTABLE`; see [Web README](../README.md). It uses a disposable synthetic fixture, separate headless Chrome profile and private artifacts. It never reads an existing browser profile or accepts an operational Core URL. Cleanup removes test containers/volume, the synthetic credential handoff, SMTP secrets/spool and the Chrome profile on success or failure.

Visual scope: the mobile feed has no horizontal overflow and the desktop calendar has seven columns. The desktop capture still contains a horizontal scrollbar in the wider shell; general responsive polish remains outside this functional integration acceptance.

## Clock-related 401 diagnosis

Earlier acceptance attempts had intermittent 401 on a recently issued token, including after a successful read using that same token. A separate synthetic-only Core wrapper recorded `ImmatureSignatureError`; no bearer token or cookie was logged. An additional 600 sequential reads with one established session passed before a newly issued token reproduced the error. Ubuntu NTP reported approximately -1.28 seconds while Windows Time was stopped. This reproduced the [previous clock conflict](CORE_SECURITY_FIXES_2026-10-22.md), rather than demonstrating a permission bypass or DTO mismatch.

Using the user's existing authorization and Windows UAC, the bounded helper started/resynced W32Time against its existing `ntp.ubuntu.com` configuration, selected Automatic startup and disabled the competing Ubuntu NTP service. Windows then reported Leap Indicator 0, Stratum 3 and an NTP offset within approximately 10 ms. This did **not** fully settle WSL: subsequent 40-second captures still observed backward steps of approximately 0.82–0.93 seconds. A temporary Hyper-V clocksource experiment did not resolve this and was restored to the original `tsc`; no boot configuration was changed.

A read-only `adjtimex(modes=0)` captured `tick=10115`, `frequency=1529415` (23.337ppm), `offset=0`, `status=8192`. The coarse tick differs from the expected 10000 us at USER_HZ 100, consistent with the measured guest clock running fast between corrections. This is an inference about the retained kernel state; the process that originally changed it has not been established. See the [Linux adjtimex interface](https://www.man7.org/linux/man-pages/man2/clock_adjtime.2.html) and [upstream WSL clock-skew issue](https://github.com/microsoft/WSL/issues/11790).

The user subsequently explicitly approved the bounded kernel reset and RTC synchronization. On 23 October at 06:28:15 UTC, `ADJ_TICK|ADJ_FREQUENCY` successfully set `tick=10000`, `frequency=0`; the helper verified both fields, then synchronized `CLOCK_REALTIME` from `/dev/rtc0` at a detected RTC second boundary (approximately 5.9 ms edge uncertainty). Ubuntu has no `hwclock`, so the helper used the standard RTC read ioctl and Python's `clock_settime`; no dependency was installed. Immediately before this reset, the kernel already differed from the earlier capture (`tick=10002`, approximately -78.29 ppm), so the earlier 10115 value was not a constant state.

A fresh 60-second probe inside the running Core container collected 2953 samples and observed **zero backward wall-clock steps**. Minimum wall-minus-monotonic step was approximately -3.69 ms, compared with the earlier -0.82 to -0.93 second corrections; total wall-minus-raw-monotonic drift was approximately 0.14 ms. The subsequent normal production acceptance passed all 22 HTTP and five Chrome groups without the earlier intermittent JWT failure. Windows Time remains Running/Automatic with Leap Indicator 0, Stratum 3; Ubuntu NTP remains disabled and clocksource remains `tsc`. Subsequent read-only `adjtimex` showed automatic rate adjustment (initially `tick=10002`, approximately -79.08 ppm; after acceptance `tick=10001`, approximately 18.69 ppm); the reset is not a permanent pin, and the actor changing that rate remains unproven. This evidence does not isolate the reset's contribution from the already-running Windows synchronization or establish stability across future sleep/restart cycles. JWT `iat`/expiry validation, cookie policy and backend authorization remain unchanged. No leeway or fixture backdating was added to mask the clock fault.

## Remaining contract boundaries

Personal history, Document, AI, Learning and Learner Intelligence require their owning service contracts. Core's current wire surface does not provide catalog editing, class rename, enrollment override, invitation history/resend/revoke, import history or data-copy execution/download. External SMTP delivery remains separate from the synthetic TLS sender test. These are not hidden by fixture fallback or empty-success summaries.
