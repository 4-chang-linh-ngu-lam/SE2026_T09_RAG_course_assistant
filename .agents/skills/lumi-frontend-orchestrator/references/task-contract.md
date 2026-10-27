# Task contract and delegation

Codex writes one bounded task per AGY invocation. Use Markdown in repo-local `docs/ai/task-*.md` (deliberately managed tracked content), or a private temp file under the repository that will be excluded before commit. Do not paste credentials or private student data.

Required sections:

1. **Task ID / module / user journey / route IDs:** give the vertical slice and exact existing paths.
2. **Baseline evidence:** current behavior, source paths, known tests, repo HEAD; distinguish verified fact vs assumption.
3. **Sources of truth:** business rule excerpts by path/heading, relevant frontend and API contracts.
4. **Worker and phase:** Flash for simple UI, Argon for difficult state/API analysis.
5. **Editable scope:** exact allowed directories/files. Everything else read-only.
6. **Prohibited changes:** backend, migrations, root AGENTS, auth/proxy/contracts without approval, live/mock boundaries, unrelated modules, Git operations.
7. **Definition of done:** real states + error handling, keyboard/responsive, no dead controls, relevant tests, no fake backend, no placeholders sold as completed features.
8. **Blocked conditions:** absent approved endpoint, unclear rule, incompatible auth, missing asset. AGY must report and stop that part, not invent an implementation.
9. **Expected response:** changed paths, behavior, tests *actually* run, blockers and remaining risks; NEVER mark tests passed if not executed.

Example AGY prompt constraints:

- 'Read the task contract and source-of-truth files. Do not modify files outside its scope. Do not run git push, commit, reset, checkout, rebase or merge. Do not call undocumented APIs. If blocked, explain in the final response and leave a clear unavailable state.'
- 'No direct fetch from product components; use the frontend DataAdapter port. No fixtures in live builds and no successful fake operations.'
- 'You own implementation only; Codex reviews and validates after the run.'
