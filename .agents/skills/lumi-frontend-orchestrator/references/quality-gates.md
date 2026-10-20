# Evidence-oriented quality gates

| Gate | Evidence needed | Fail / block if |
| --- | --- | --- |
| Branch and change scope | `git branch --show-current`, HEAD, clean pre-existing diff accounted for | wrong branch / AGY overwrote pre-existing work |
| Business | code compared to `BUSINESS_RULES.md` | invented roles, student self sign-up, join code, unofficial exam behavior |
| Integration boundary | `npm run check:boundaries`, targeted source review | component fetch, fixture fallback, service credential in browser, fake endpoint |
| Types and unit tests | actual `npm run check` stdout/exit | tests skipped or unverified failures |
| Release | `NEXT_PUBLIC_DATA_MODE=live`; `npm run build` (includes release canary scan) | mock preview used as release or canary detected |
| UX | keyboard, mobile, desktop, loading/empty/error/403/409, focus, navigation; manual browser evidence | a polished static screen with dead controls |
| Backend | configured Core, real response and negative paths, cookie/origin validation | adapter exists but endpoint not approved/deployed or only mocks tested |
| Security | inspected diff and config; fail-closed permissions | secrets, cross-role data disclosure, unsupported retries, weak permission claims |
| Delivery | changed-file list, tests, known blockers, user approval for push | blanket 'done' claim with no evidence |

`npm run check` and `npm run build` use the checked-out project script definitions; no assumption of lint/test script beyond those found in `package.json`. `git diff --check` should also pass. For UI browser QA, use a local actual browser/browser test mechanism already available and provide screenshots or step-by-step observations. Codex does not call an absent tool and should state when browser inspection is unavailable.
