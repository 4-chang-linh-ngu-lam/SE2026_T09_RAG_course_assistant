# Task UI-SOURCE-REVIEW-01

## Module, journey and baseline
Document source management D03–D06 (t.libraryDocument) and the shared Administration history UI. Current branch frontend1, baseline HEAD 9dc547c467c093940fcdc9873a14cf45ca1f6a28. A previous AGY run generated four presentational files; Codex has inspected them and found the concrete issues below. This is repair iteration 1. The components are not integrated yet; no backend success is claimed.

## Worker and sources
Implement with gemini-3.8-flash-high, UI only. Read the new repository skill, root/web AGENTS. Relevant design records: D:/app/cnpm/frontend/artifacts/frontend-implementation/antigravity/inputs/ui-source-and-admin/t.libraryDocument.json and a.classSettings.json; their verified HTML is authoritative for visuals. Current domain models in apps/web/src/lib/domain.ts. Codex owns all data, permission and async logic.

## Editable scope
- apps/web/src/features/document/components/source-management-ui.tsx
- apps/web/src/features/document/components/source-management-ui.css
- apps/web/src/features/classroom-admin/presentation/history-panel.tsx
- apps/web/src/features/classroom-admin/presentation/history-panel.css

All other files are read-only. No shell commands, servers, npm, dependency/config changes, network calls, adapters, mocks, contracts, permissions, global model/settings, commits or Git mutations. Use file read/edit tools only. Return the report in your response; no extra report file is required. Existing worktree changes outside these files belong to the user and must be preserved.

## Required corrections
1. CSS `.lumi-source-table tr.is-serving td` has invalid `background: #eff6ff/30`; replace with a valid subtle blue CSS color.
2. Retry banner and version table currently share `id=ux-doc-retry-vN` for the same version. Keep the banner ID; make each table retry ID `ux-doc-table-retry-vN`. All IDs must be unique when both render.
3. Failure fallback must not invent a parsing error. Use an honest unspecified-failure explanation when `version.errorMessage` is absent.
4. Failure copy must not claim every shared class uses the same serving version; each grant has its own version. Explain that each class keeps its currently granted version, with per-class details below. When servingVersion is null, clearly say no serving version is available. Keep the component purely presentational.
5. SourceDocumentSummary: add optional `shareUnavailableReason?:string`; when canShare is false, display/use the supplied reason without guessing it is a permission failure. Root will supply actual eligibility and reason.
6. AdministrationHistoryPanel can appear twice on one page. Use React useId for its aria-labelledby/title ID to avoid duplicate IDs. Format valid supplied ISO times readably in Vietnamese with Asia/Ho_Chi_Minh timezone, retain dateTime as the original ISO string. Missing/invalid times must not become a fabricated date.
7. Ensure source cards, grants, filenames and history panels have min-width:0 / wrapping where needed so a long filename or class name cannot stretch the page at390px. Keep the version table's local horizontal scroll and its accessible focus region. Preserve existing callback props, busy states and keyboard semantics.

## Definition of done / response
Fix the four allowed files only, with no stubbed data or behavior. State exact changes and files. Do not claim npm/type/browser checks passed: Codex runs them after your edit. If a required asset or public contract is missing, report it; do not invent one. No global config or approval changes.
