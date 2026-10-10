# Agent Instructions — RAG Course Assistant

Read `docs/architect/BUSINESS_RULES.md` (authoritative product constraints), `docs/architect/ARCHITECTURE.md` (architecture proposal/status), `docs/tasks/TASK_PLAN.md` (provisional plan) and `docs/CONTRIBUTING.md` (Git workflow) before modifying code.

- Never invent, relax, or silently modify an accepted business rule. Cite Rule IDs in plans/PRs.
- Distinguish approved decisions from [ĐỀ XUẤT] and [CHƯA CHỐT]. Ask for approval before introducing unapproved architecture decisions.
- One large feature per branch, multiple small Tasks/meaningful commits per feature. Branch from main; do not push directly to main.
- Do not merge PRs, change branch protections, deploy, or perform destructive operations without explicit human approval.
- Do not modify unrelated modules. Communicate shared API/schema changes and test consumers.
- Enforce class/document permissions at Backend and before retrieval/source opening; never leak revoked content.
- Preserve immutable assessment versions, attempt history, grading accountability, privacy, and audit requirements.
- Write unit/integration tests for authorization, grading, error paths, and document revocation.
- Never expose credentials or private conversations in commits, logs, fixtures, or prompts.
- Human owner reviews AI-generated code before PR. Use actual tests; never claim a check passed without running it.
- Web-first; Mobile only after Web is stable and the team approves the scope.
- No artificial commits for course grading; show genuine work through issues, commits, reviews and incremental demos.
