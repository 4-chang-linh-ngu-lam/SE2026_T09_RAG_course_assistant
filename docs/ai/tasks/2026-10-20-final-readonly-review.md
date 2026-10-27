# Bounded independent review (read-only)
Repo: D:/app/cnpm/SE2026_T09_RAG_course_assistant, branch frontend1. Use file READ tools ONLY. Do not invoke RunCommand, terminal, shell or Git, do not write any file (including plans/reports), do not edit settings/permissions/models. Codex owns logic; review findings are advisory and Codex verifies. Return the requested structured JSON only through your response.
Read root/web AGENTS, orchestrator SKILL. Review only these current files for concrete regressions; no full-monorepo inventory:
- apps/web/src/lib/navigation.ts
- apps/web/src/components/route-screen.tsx
- apps/web/src/features/document/views/student-reader-view.tsx
- apps/web/src/features/document/reader-operation-scope.ts
- apps/web/src/features/document/views/teacher-library-document-view.tsx
- apps/web/src/features/notification/use-notification-state.ts
- apps/web/src/lib/notification-read-controller.ts
- apps/web/src/features/notification/notification-center.tsx
- apps/web/src/lib/date-scope.ts
- apps/web/src/features/intelligence/index.tsx (only DateFilter, Audit, IntelligenceFeature)
- apps/web/src/lib/data/integrations.ts

Focus on substantive bugs: stale actor/resource ACKs, navigation/draft context, pending/unknown/rejected outcomes, query sanitization, permission/role bypass, fake live success, lifecycle/StrictMode races, controlled UI focus/keyboard semantics. No speculative architecture redesign or suggestions to invent backend rules. Most service contracts are unavailable and live adapters deliberately return unavailable; that is known, not a new defect. UI is AGY-authored, Codex integrated it. Current unit/check/browser acceptance is being executed by Codex; do not claim you ran it. Report only verified source-backed findings with exact path, code evidence and smallest proposed fix. If no concrete issue, pass with empty findings. This is not blanket frontend/backend certification.
