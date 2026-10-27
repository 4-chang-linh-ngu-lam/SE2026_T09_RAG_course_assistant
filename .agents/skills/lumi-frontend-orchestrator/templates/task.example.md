# LF-001 — Student home: inventory and one cohesive UI improvement

**Phase:** Start with Audit (Flash) to map `s.home`, then create a narrower Implement contract after reviewing the inventory.
**Route:** `/student`, `s.home`
**Goal:** Determine what is fully implemented vs generic/unavailable; propose the smallest contract-safe improvement to user journey, responsive behavior and honest states.

## Source of truth
- Root `AGENTS.md`
- `apps/web/AGENTS.md`
- `docs/architect/BUSINESS_RULES.md`
- `apps/web/docs/FRONTEND.md`
- `apps/web/src/config/routes.ts` (verify exact source)
- `apps/web/src/features/index.tsx`
- Related student and shared feature files
- `apps/web/src/lib/data/integrations.ts`

## Editable scope
For Audit: NONE, read-only. In a later Implement task, Codex must pin exact paths based on findings; do not use an open-ended `apps/web/**` wildcard.

## Acceptance
- Trace `/student` entry to `RouteScreen`, target `FeatureEntry`, relevant port, and live/mock semantics.
- Identify which UI interactions are working, dead, or accurately disabled.
- Assess loading/empty/error/permission states and mobile/keyboard behavior.
- Propose up to three independently testable follow-up tasks with exact paths and contract dependencies.
- If a backend operation is pending, recommend a truthful unavailable state rather than guessing an endpoint.

## Prohibitions
No writes during Audit. No backend/API spec changes. No credential inspection. No git mutations.
