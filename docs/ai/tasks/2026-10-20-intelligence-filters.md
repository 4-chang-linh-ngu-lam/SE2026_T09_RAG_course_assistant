IMPORTANT: Repair attempt 1 after the prior run stopped with denied action RunCommand and NO source changes. DO NOT repeat that action. Use only file read/edit tools; no command tool even for reading or listing. All paths below are relative to D:/app/cnpm/SE2026_T09_RAG_course_assistant. No need to inspect Git, shell or environment.

# UI-INTELLIGENCE-FILTERS-01

AGY gemini-3.8-flash-high implements presentation only; Codex owns filtering, date conversion, state, adapters and tests. Read root/web AGENTS, .agents/skills/lumi-frontend-orchestrator/SKILL.md, relevant domain types in apps/web/src/lib/intelligence.ts and current feature/CSS. Verified design records are under D:/app/cnpm/frontend/artifacts/frontend-implementation/antigravity/inputs/ui-intelligence-filters for s.progress, t.analytics and a.audit; inspect their referenced HTML. Preserve the app's Lumi typography/palette. Never treat reference counts, actors or dates as runtime values.

Exact editable scope (new files):
- apps/web/src/features/intelligence/scope-filters.tsx
- apps/web/src/features/intelligence/scope-filters.css
- apps/web/src/features/intelligence/intelligence.css (only replace `align-items:end` with `align-items:flex-end` to resolve the verified autoprefixer warning; preserve all other styling)

All other files read-only. No adapters/network, data mocks, permissions, business state/date parsing, tests, shell commands, Git, dependencies, root CSS/config or global settings. Root integrates and checks. Return summary directly, no report file.

Export LearningScopeFilters with exported props:
```ts
{
 fromDate:string; toDate:string;
 activities:readonly ActivityOption[];
 selectedResourceIds:readonly string[]; // [] means all activities
 appliedSummary:string;
 error:string|null;
 busy?:boolean;
 onFromChange(value:string):void;
 onToChange(value:string):void;
 onResourcesChange(ids:string[]):void;
 onApply():void;
}
```
ActivityOption is imported type from @/lib/intelligence. Render a semantic form with labels Từ ngày / Đến hết ngày, native date inputs, actual activity choices with kind labels (Luyện tập / Kiểm tra chính thức / Bài tập tự luận), clear-all selection action meaning Tất cả hoạt động. Controlled checkbox interactions may call onResourcesChange with the updated supplied list, but do not retain local business state or derive results. Empty activities must be explained honestly. Submission prevents default and calls onApply. Supplied error shows role=alert, disables submit; busy also disables controls. Render appliedSummary verbatim (not a fake count). Keep existing class in-filters on outer form so existing journey date selectors still work; its first two labels must be the dates in the existing order. Use scoped CSS prefix lumi-scope-. UI must wrap long labels, show focus, support 390/1024/1440 with no page overflow or root clipping.

Export AuditDateRange with props:
```ts
{ fromDate:string;toDate:string;error:string|null;onFromChange(value:string):void;onToChange(value:string):void;onClear():void; }
```
A compact controlled fieldset with legend Khoảng thời gian, labeled optional date inputs Từ ngày / Đến hết ngày, supplied validation error and button Xóa lọc ngày. No own state, date parsing or filtering. Root includes it inside an existing audit filters container. No submit/network actions. A11y unique IDs via useId; associate errors/help with controls. Show no sample dates, generated audit or totals. No duplicate h1, placeholder buttons, Tailwind assumptions or CSS dependencies outside the two allowed files.
