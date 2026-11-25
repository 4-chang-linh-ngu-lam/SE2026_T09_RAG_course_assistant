# Lumi UI/UX refinement — 15 November 2026

## Scope and ownership

Frontend presentation and the existing user journeys only. The 71 route definitions, feature set, business rules, backend contracts, adapter interface, permissions and live/mock selection remain the baseline. Thin `app/**/page.tsx` entry points continue to dispatch to the owning feature.

Baseline: branch `assignment/23001878-vt033-notification-config`, HEAD `c970355e5d7654b5f27b668f9bd087126fa2ab06`, initially clean worktree. No commit, push or branch change is part of this work.

The user selected AGY `gemini-4-hydrogen-xhigh` for UI implementation and `gemini-4-argon-high` for UX/logic review, and explicitly authorized sending frontend source and relevant documentation to AGY. Codex owns integration, behavioral fixes and verification. Workers use bounded file allowlists; provider and approval configuration are unchanged. Temporary launchers/task files are local working artifacts, not product code.

## Implementation ledger

`UI-only` means the presentation is implemented and source-reviewed. It does not certify a browser journey or a live backend transaction. The shared foundation applies to every route; each group also has feature-owned presentation styles.

| Group | Existing route IDs | Status |
| --- | --- | --- |
| Authentication | `auth.login`, `auth.activate`, `auth.recover`, `auth.reset`, `auth.invitation` | UI-only |
| Classroom | `s.home`, `s.classes`, `s.overview`, `s.history`, `t.home`, `t.classes`, `t.overview` | UI-only |
| Communication | `s.feed`, `t.feed`, `s.calendar`, `t.calendar`, `account.calendar`, `account.notifications` | UI-only |
| Documents and notes | `t.library`, `t.libraryDocument`, `t.documents`, `s.documents`, `s.reader`, `s.notes` | UI-only |
| Tutor | `s.tutor`, `t.tutor` | UI-only |
| Practice and activities | `s.practice`, `s.practiceAttempt`, `s.practiceResult`, `t.activities`, `t.practiceEditor` | UI-only |
| Official assessments | `s.assessments`, `s.assessment`, `s.examAttempt`, `s.receipt`, `s.examResult`, `t.assessmentEditor`, `t.assessmentApproval`, `t.examGrading` | UI-only |
| Assignment and grading | `s.assignments`, `s.assignment`, `s.historyResult`, `t.assignmentEditor`, `t.gradingQueue`, `t.assignmentGrading`, `t.correction`, `t.correctionApproval` | UI-only |
| Account and provisioning | `account.profile`, `account.requests`, `a.newStudent` | UI-only |
| Account administration | `a.accounts`, `a.account`, `a.legacy`, `a.staffInvite`, `a.importNew`, `a.import` | UI-only |
| Classroom administration | `a.catalog`, `a.homerooms`, `a.homeroom`, `a.classes`, `a.newClass`, `a.classSettings`, `a.enrollment`, `a.lifecycle` | UI-only |
| Evidence, audit and reports | `s.progress`, `t.analytics`, `t.studentAnalytics`, `a.dataRequests`, `a.audit`, `a.reports`, `a.exports` | UI-only |

## Design and UX changes

- Canonical tokens and shared surfaces live in `src/styles/lumi-foundation.css`, imported once after `app/globals.css`. Blue remains the main action/navigation color; teal identifies Tutor. Typography, spacing, form controls, focus, disabled states, notices, empty/loading surfaces and dialogs use the same foundation.
- Navigation retains existing destinations and role restrictions. Desktop profile access belongs to the sidebar footer; mobile navigation retains its profile destination. Skip links target a focusable main region on auth/session/access/loading/error screens as well as the authenticated shell.
- Classroom cards and tasks expose the existing class, status and action hierarchy. Container queries adapt home/overview columns to usable content width. Calendar CSS now matches actual JSX selectors, including the seven-day grid, legend and selected view. Calendar date/list selection supports keyboard input and local calendar scrolling is labeled.
- Document/Tutor utilities without a CSS implementation were replaced with owned semantic classes. Reader typography, source/version metadata, toolbar controls and panel breakpoints were refined. Notes, citations, unavailable services, revoked sources and official-assessment Tutor locks keep their existing meaning. Privacy copy is real text, not CSS-generated content.
- Feed mutations require matching current active class context in the UI; archived or unverifiable context is read-only. The backend remains authoritative. Errors appear at the active form/post/dialog, and unsent drafts use the existing navigation guard.
- Personal note/bookmark links preserve captured version and page. Editing passes those locators through the existing port, protects unsaved text and keeps save/delete errors in the active dialog. Deletion requires confirmation.
- Practice layout styles moved from inline declarations into feature CSS. Question options, true/false targets, save/feedback labels, palette and results use the shared hierarchy. The save indicator derives from the existing acknowledgement/controller state and acknowledged-answer equality; pending, unknown or failed saves cannot acquire a saved appearance through translated text matching. Assessment and Assignment styles scope overlapping `.as-*` names to their owning feature, retaining focused exam layouts, timer and existing confirmations.
- Account, import, roster, enrollment, lifecycle, audit and report surfaces use readable filters/tables/forms with local scrolling, wrapping actions and consistent semantic statuses. Personal-data requests distinguish pending/review/completed/rejected instead of giving every status the default green badge. Current Admin class navigation is identified through `aria-current`. Read-only fields and one-time-code handoff remain distinct from disabled controls; confirmation and reconciliation behavior is preserved.

## Verification and limits

| Check | Observed result |
| --- | --- |
| Dependency setup | `npm.cmd ci --no-audit --no-fund`: exit 0; package lock unchanged |
| Baseline `npm.cmd run check` | Boundaries, TypeScript, 259/259 tests passed after resolving sandbox `tsx` user-info access |
| Workspace `npm.cmd run check` | Boundaries, TypeScript, 262/262 tests passed, including new current-class feed and historical source-link regressions |
| Foundation live build | `NEXT_PUBLIC_DATA_MODE=live`, `npm.cmd run build`: exit 0; release fixture-marker scan passed |
| Preview HTTP smoke | `GET http://127.0.0.1:4179/login`: HTTP 200 |
| Static review | Worker presentation diffs reviewed separately from Codex behavioral edits; handlers/adapter calls compared in the modified classroom, document, Tutor and practice views |
| Final `npm.cmd run check` | Exit 0: boundaries and TypeScript passed; 262/262 tests, 0 failed/skipped |
| Final live `npm.cmd run build` | Exit 0: compiled successfully (25.4s), generated pages and passed release fixture-marker scan; no compiler warnings in the final log |
| `git diff --check` | Exit 0 |
| Route ledger check | 71/71 existing route IDs; no missing, unknown or duplicate IDs |
| Final Argon review | `gemini-4-argon-high`: verdict `pass`, no introduced findings; read-only source review, not runtime certification |
| Current browser/visual verification | Blocked: browser host unavailable; native Computer Use then stopped because it could not determine the current Windows browser URL confidently enough to enforce policy. No current responsive screenshots or interactive browser pass is claimed. |

Preview uses the explicit in-memory development adapter. The live build is a separate artifact and does not establish Core/service availability. Current readiness remains defined by `src/lib/data/integrations.ts`: Document, Tutor and Learning are pending contract; several Intelligence operations are pending service or policy. No endpoint, retention policy, analytics value or fake successful operation was added.

Argon's audit is advisory. Findings about the actual calendar selectors, undefined utilities and note locators were checked against source before action. Its claims about unavailable Social/Calendar/Notification contracts and an obsolete multi-bar shell/reader layout were rejected because they did not match current source and integration declarations. The assignment audience currently provides opaque user IDs without display names; this presentation task does not invent identities or expand that data contract.

The remaining acceptance work is a visual/keyboard/responsive browser review at 320/390/768/1024/1440 CSS px and configured live backend journeys. Historical acceptance in `FRONTEND.md` is not reused as evidence for these changes.

## Worker and command evidence

Argon performed one initial audit and one final review. Hydrogen performed five sequential bounded implementation runs: foundation/auth, classroom/communication, document/Tutor, learning/assessment/assignment, and administration/account/evidence. All seven AGY results reported `SUCCESS`, CLI exit 0, a nonempty response and zero denied actions. Earlier outer Windows PowerShell invocations reported exit 1 while forwarding AGY's informational `Fetching available models...` stderr; this was not treated as passing verification. The final review launcher returned exit 0. Codex accepted the source changes only after inspecting diffs and running the actual checks above.

Commands ran from `apps/web` unless specified:

```powershell
npm.cmd ci --no-audit --no-fund
npm.cmd run check
$env:NEXT_PUBLIC_DATA_MODE='live'
npm.cmd run build
```

Repository checks: `git diff --check`; `git diff --name-only -- services docs/architect apps/web/dev apps/web/src/lib/data apps/web/src/lib/api apps/web/src/config apps/web/package.json apps/web/package-lock.json apps/web/next.config.mjs` returned no paths. Branch and HEAD stayed at the baseline. No API/schema/route/data-adapter/package/backend changes, new dependencies, commit or push were made. `.gitignore` now excludes the existing `.next-preview` development cache to prevent generated artifacts entering the diff.

Local preview command: `node scripts/dev-mock.mjs --hostname 127.0.0.1 --port 4179`. The preview is intentionally mock-backed and remains separate from the verified live build.

## Changed files

- `.gitignore`
- `apps/web/app/error.tsx`
- `apps/web/app/globals.css`
- `apps/web/app/layout.tsx`
- `apps/web/app/loading.tsx`
- `apps/web/app/not-found.tsx`
- `apps/web/docs/FRONTEND.md`
- `apps/web/docs/UI_UX_REFINEMENT.md`
- `apps/web/src/components/route-screen.tsx`
- `apps/web/src/components/session-redirect.tsx`
- `apps/web/src/components/shell.tsx`
- `apps/web/src/components/ui.tsx`
- `apps/web/src/features/accounts/accounts.css`
- `apps/web/src/features/assessment/assessment.css`
- `apps/web/src/features/assignment/assignment.css`
- `apps/web/src/features/classroom/class-overview.tsx`
- `apps/web/src/features/classroom/empty-states.css`
- `apps/web/src/features/classroom/index.tsx`
- `apps/web/src/features/classroom/student-classes.tsx`
- `apps/web/src/features/classroom/student-home.tsx`
- `apps/web/src/features/classroom/teacher-classes.tsx`
- `apps/web/src/features/classroom/teacher-home.tsx`
- `apps/web/src/features/classroom/teacher-overview.tsx`
- `apps/web/src/features/classroom/workspace.css`
- `apps/web/src/features/classroom-admin/classroom-admin.css`
- `apps/web/src/features/classroom-admin/common.tsx`
- `apps/web/src/features/classroom-admin/presentation/history-panel.css`
- `apps/web/src/features/document/class-source-preview.css`
- `apps/web/src/features/document/components/source-management-ui.css`
- `apps/web/src/features/document/library.css`
- `apps/web/src/features/document/reader.css`
- `apps/web/src/features/document/views/student-class-documents-view.tsx`
- `apps/web/src/features/document/views/student-notes-view.tsx`
- `apps/web/src/features/document/views/student-reader-view.tsx`
- `apps/web/src/features/document/views/teacher-class-documents-view.tsx`
- `apps/web/src/features/document/views/teacher-library-view.tsx`
- `apps/web/src/features/identity/account-workspace.css`
- `apps/web/src/features/identity/auth-view.tsx`
- `apps/web/src/features/identity/data-requests.css`
- `apps/web/src/features/identity/data-requests.tsx`
- `apps/web/src/features/identity/profile.tsx`
- `apps/web/src/features/identity/provisioning.tsx`
- `apps/web/src/features/identity/request-copy.tsx`
- `apps/web/src/features/intelligence/intelligence.css`
- `apps/web/src/features/intelligence/scope-filters.css`
- `apps/web/src/features/learning/components/question-renderer.tsx`
- `apps/web/src/features/learning/index.tsx`
- `apps/web/src/features/learning/learning-workspace.css`
- `apps/web/src/features/learning/views/practice-authoring.css`
- `apps/web/src/features/learning/views/student-practice-attempt-view.tsx`
- `apps/web/src/features/learning/views/student-practice-list-view.tsx`
- `apps/web/src/features/learning/views/student-practice-result-view.tsx`
- `apps/web/src/features/learning/views/teacher-practice-editor-view.tsx`
- `apps/web/src/features/notification/notification-center.css`
- `apps/web/src/features/social/calendar.tsx`
- `apps/web/src/features/social/feed.tsx`
- `apps/web/src/features/social/index.tsx`
- `apps/web/src/features/social/workspace.css`
- `apps/web/src/features/tutor/tutor.css`
- `apps/web/src/features/tutor/views/student-tutor-workspace.tsx`
- `apps/web/src/features/tutor/views/teacher-tutor-config-view.tsx`
- `apps/web/src/lib/document-preview.ts`
- `apps/web/src/lib/feed-post-state.ts`
- `apps/web/src/styles/lumi-foundation.css`
- `apps/web/tests/feed-post-state.test.ts`
- `apps/web/tests/personal-source-navigation.test.ts`
