# Task UI-NOTIFICATION-01

## Module / journey / baseline
Notification center `account.notifications` at `/notifications`. Current branch frontend1. Codex has implemented `src/lib/notification-read-controller.ts` with deferred tests; its state is authoritative. The existing NotificationFeature still performs optimistic reads and will be replaced by a thin Codex controller bridge. You generate its controlled UI only. Do not change the existing feature entry/controller.

## Worker / phase / references
AGY gemini-3.8-flash-high, Implement. Read root and web AGENTS and the repository `lumi-frontend-orchestrator/SKILL.md`. Read the compact verified design record at `D:/app/cnpm/frontend/artifacts/frontend-implementation/antigravity/inputs/ui-notification/account.notifications.json` and its referenced HTML (C08), plus current `src/features/notification/index.tsx`, notification styles in `app/globals.css`, `src/lib/domain.ts`, and the public `NotificationReadIssue` type. Reuse the current Lumi typography, shared Icon and semantic buttons/cards. Sample actors, IDs, dates, counts and content in the design are not runtime data.

## Exact editable scope
- apps/web/src/features/notification/notification-center.tsx
- apps/web/src/features/notification/notification-center.css

All other files are read-only. No dependency/globalCSS/config/model/provider/approval changes, backend/contracts, data adapters/mocks, network calls, state machines, tests, Git operations or shell/server/build commands. Root will wire and run tests. Do not write a report file; respond with the implementation summary and real limitations.

## Required exported UI
Export `NotificationCenter` and `NotificationCenterProps`. Import `NotificationItem` from `@/lib/domain` and `NotificationReadIssue` from `@/lib/notification-read-controller` as types. Use controlled props exactly:

```ts
type NotificationCenterProps = {
  loadState: 'loading' | 'unavailable' | 'ready';
  loadMessage?: string;
  items: readonly Readonly<NotificationItem>[]; // already filtered by root
  selected: Readonly<NotificationItem> | null;
  filter: 'all' | 'unread';
  totalCount: number;
  unreadCount: number;
  busy: boolean;
  issue: NotificationReadIssue | null;
  snapshotError: string | null;
  accessNotice: string | null;
  onSelect(id: string): void;
  onFilter(filter: 'all' | 'unread'): void;
  onNavigate(item: Readonly<NotificationItem>): void;
  onMarkAll(): void;
  onRetry(): void;
  onReconcile(): void;
  onRefresh(): void;
};
```

No adapter, router, session, storage or mutation implementation. Do not cache or edit notification objects or infer read success. Root changes `item.isRead` only after ACK. You may format timestamps/display labels, render supplied states, focus the selected detail region, and use useId for accessible IDs.

## UI acceptance
1. Canonical master/detail card layout: list with counts/tabs/category/status/date and a clear selected item; detail with actual title/content/class/date and the supplied target action. No duplicate h1: the shared route provides the page heading; use h2 for panel headings.
2. Loading, unavailable+retry, empty total, empty unread filter, selected detail, mutation pending, rejected retry, unknown read-state reconciliation, snapshot-refresh error and denied navigation all have readable Vietnamese presentation. Reuse StatePanel/ErrorNotice where helpful.
3. Busy state is visible and disables repeat mark-read actions; unknown state offers `onReconcile`, never an automatic retry. Rejected offers `onRetry`. Refresh calls `onRefresh`. Never claim a successful read before item.isRead changes. All counts are supplied props, not generated samples.
4. Semantic list/buttons, keyboard navigation and focus indication, aria-current on selected item, aria-selected on filter tabs, correct screen-reader labels and alert/status areas. Category badges use Vietnamese labels and text, not just color.
5. Desktop at1440/1024, mobile at390: bounded list scrolling where useful, content/details and belowfold actions reachable, long titles/class names/URLs wrap. Use real scoped CSS prefix `lumi-notification-`, min-width:0, explicit local overflow; no root clipping or Tailwind assumptions.
6. Keep details read-only. The related-content action calls `onNavigate(selected)`; root validates route/roles. Render it only when actual selected.targetHref exists. Do not invent links or pretend a notification target is authorized because it is visible.

## Done / blocked / response
Implement the two allowed files completely, no placeholder buttons or fabricated content. If a public prop is insufficient, explain the required change instead of adding backend calls or changing the controller. Report exact files and what root must wire. Do not claim type/build/browser tests: root performs them after your edit.
