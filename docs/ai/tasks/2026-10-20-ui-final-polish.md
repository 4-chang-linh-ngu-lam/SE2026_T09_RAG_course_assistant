# UI-REVIEW-POLISH-01

Worker AGY gemini-3.8-flash-high. UI only. Read root/web AGENTS and repo orchestrator skill using FILE TOOLS ONLY. Never invoke RunCommand/command/terminal/shell, including read-only commands, listing, Git or tests. Codex handles logic/integration/checks. Repo D:/app/cnpm/SE2026_T09_RAG_course_assistant.

Exact editable scope:
- apps/web/src/features/notification/notification-center.tsx
- apps/web/src/features/notification/notification-center.css
- apps/web/src/components/route-screen.tsx (ONLY remove the duplicate a.accounts provision CTA described below; no other edits)

All other files are read-only. Do not alter controllers, ports, fixtures, session/permissions, adapters, dependencies, global styles, model/provider/approval settings, tests, contracts. No reports on disk; return a concise summary.

Codex reviewed the actual rendered notification UI at1440/1024/390 and the controlled props work. Fix these concrete presentation issues (repair1):
1. Generic ASSIGNMENT label must be 'Bài tập', not 'Hạn nộp bài tập' (published results also use this category). EXAM must be 'Bài kiểm tra', not 'Kiểm tra định kỳ'. Continue respecting actual custom categoryLabel when supplied. Do not infer deadlines/exam types.
2. Do not move focus automatically into the detail panel on the initial incoming selection or an automatic fallback selection. Move focus after an actual user list activation only; keep tracking this as UI interaction state/ref. Preserve keyboard activation. Initial mobile page should start at the heading/list, not jump below it.
3. Each interactive notification should be a native type=button within the semantic role=listitem wrapper (keep .lumi-notification-item on the actionable control, existing is-read/is-unread/aria-current classes and selected styling so QA/visual behavior remains). No nested interactive controls. Use spans instead of invalid headings inside buttons as needed, maintain visible title styling, reset button font/color/alignment/width in scoped CSS. Native Enter/Space behavior should invoke onSelect exactly once.
4. Tabs need roving tabIndex and ArrowLeft/ArrowRight/Home/End navigation, focus plus onFilter for keyboard selection; maintain aria-selected/controls and native button semantics. No data fetching or local filtering.
5. Disable mark-all while issue.outcome==='unknown'; explicit reconciliation must be the available action. Root already prevents unsafe writes, UI must explain state clearly. Keep list selection possible to inspect details.
6. Invalid supplied createdAt must render a readable 'Chưa có thời gian' and not 'Invalid Date' or a fabricated timestamp. Keep valid ISO dateTime values; omit dateTime for invalid dates. Display functions only; no business date decisions.
7. On account list, both RouteScreen's generic page-heading and the accounts feature render the same 'Cấp tài khoản học sinh' CTA. Keep the actual feature's CTA. In route-screen.tsx remove ONLY `{routeId === 'a.accounts' && <Link className="button primary" href="/admin/accounts/students/new">Cấp tài khoản học sinh</Link>}`. Preserve all route/auth/heading ownership logic.

Maintain scoped CSS, no root clipping, long-text wrapping at390, focus outlines, callback props and pending/error/empty/unknown states. No duplicate h1. No npm/test/build claims; Codex reruns acceptance.
