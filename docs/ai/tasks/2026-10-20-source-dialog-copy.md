# Source dialog copy, UI-only micro task
Use gemini-3.8-flash-high. Repo D:/app/cnpm/SE2026_T09_RAG_course_assistant. Read root/web AGENTS and repo orchestrator skill with file READ tools. Never use RunCommand/terminal/shell/Git/tests or write reports. Only editable file: apps/web/src/features/document/views/teacher-library-document-view.tsx. Do not touch logic, imports, callbacks, scope guards, adapters, busy/disabled states or any other file.
Make ONLY these Vietnamese UI text replacements in the existing dialog JSX:
1. In revoke warning replace the visible strong text '?nh h??ng b?o m?t (Rule B6):' with '?nh h??ng khi thu h?i:'. Keep the actual explanation of lost source access intact; no internal rule code should appear to the user.
2. Delete dialog title currently 'X?c nh?n g? kh?i b?ng tin t?i li?u ngu?n' must be 'X?c nh?n x?a t?i li?u ngu?n'.
3. Delete confirmation sentence 'B?n c? ch?c ch?n mu?n g? kh?i b?ng tin t?i li?u' must be 'B?n c? ch?c ch?n mu?n x?a t?i li?u ngu?n'. Keep doc.title interpolation and warning/action semantics.
Return concise changed text/file summary. No other refactor, formatting sweep, feature or business-rule changes. Codex runs checks.
