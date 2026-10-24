# Login roles and email onboarding — 23 October 2026

The generic login activation link sent staff to Student activation. Staff invitation email contained only a token, so recipients could submit an ADMIN_INVITATION credential to the Student-only endpoint and receive an invalid-token error.

## Result

- The Student login tab retains `/activate`, explicitly labelled **Kích hoạt tài khoản học sinh**. The Teacher/Admin tab hides that link and explains the invitation-email workflow. Student onboarding still uses the Admin-issued username/code; it does not require email.
- Staff invitation email links to the configured Web origin at `/staff/invitation#token=...`. Password-recovery email links to `/reset-password#token=...`. Both include expiry information. The link carries the credential, so recipients choose a password without copying a token between screens.
- `WEB_ORIGIN` is shared by Core and Web in Compose. Core validates an explicit HTTP(S) origin without credentials, path, query, fragment, whitespace or ambiguous backslash/encoded-host syntax. Email destinations never come from an untrusted request Host/Origin. A missing origin rejects invitation/reset delivery.
- The browser reads the fragment into memory and removes it from the address bar while preserving Next history state. The fragment is not sent as the HTTP request URL or Referer. Previously supported query-token links still work and are scrubbed too. A page visit does not consume a token; the user must submit a new password. Single-use, purpose, expiry, lock and session-revocation checks remain authoritative in Core.
- Legacy email verification has no approved Web page and retains its separate behavior. No endpoint, DTO, permission, Student self-registration or staff resend/revoke API was added. The proxy remains the approved 63 operations.

Review owners: Core.Identity, Common/configuration, Compose and Web.Identity. Business Rules and applied migrations are unchanged. No real email, invitation or token was sent/redeemed by the agent against an operational user account during acceptance.

## Verification

- `npm.cmd run check`: **329 passed**, zero failures/skips; boundaries and TypeScript passed.
- Focused backend tests `tests/identity/test_email_origin.py` and `tests/identity/test_http_security.py`: **51 passed**, warnings treated as errors. Coverage includes invalid origins, correct purpose/route/origin, URL encoding, fragment-only credentials, missing origin before SMTP, TLS and secret-free error behavior. This is a focused regression run, not a full backend suite run.
- Windows Python could not initially collect the backend tests because its runtime dependencies were incomplete. The final run used the existing Core Linux image and existing pure-Python pytest tools mounted read-only, with no dependency installation or operational database access.
- `CORE_BROWSER_EXECUTABLE=<installed Chrome>` with `npm.cmd run test:core`: **exit 0**. Fresh production live build/release, installed non-root Core package, migration check and repeat-safe synthetic seed passed.
- **22 HTTP groups passed**: seven groups covering 46 Classroom/Social/Administration operations, seven Notifications groups, eight Identity/security groups. Synthetic TLS SMTP and database outage/recovery passed.
- **Six real Chrome groups passed**, zero uncaught exceptions, desktop/mobile widths 1440/390. The added group checks the activation link while switching Student/Staff tabs, follows the actual emailed invitation link, checks URL cleanup/autofill, sets a password, logs in and rejects a replay. No credential query parameter was observed in browser network requests, and no local/session storage credential was introduced. The earlier five groups continue to cover persistence, Student social flows, offline reconciliation, Teacher calendar and lock/revocation.
- `ruff check`, `ruff format --check` on changed backend files and `git diff --check`: passed.

Private acceptance artifacts: temporary directory basename `lumi-core-smoke-f3Wiv7`. Existing test cleanup removes the fixture containers/volume, browser profile, SMTP key/spool and credential handoff. No credentials, private email addresses or SMTP configuration are included in this report.

The updated package/template is installed in both local environments: Web/Core login/readiness on3000/8000 and3100/8100 returned200; anonymous proxied Admin access returned401. Core reports the matching configured origin in each environment. The main private SMTP configuration and both databases were preserved. Final cleanup found zero test containers, test volumes, sensitive fixture files or browser profiles. See [machine-readable evidence](evidence/core-email-link-flow-2026-10-23.json).

## Compatibility

Local services must be rebuilt to use the new Core configuration/email template; source changes alone do not change the installed container package. Previously delivered email remains unchanged and its token keeps its original purpose/expiry. A valid old staff token can still be entered at `/staff/invitation` on the environment that issued it; it must not be entered at Student `/activate`. Existing accounts are not deleted or recreated to resend invitations.
