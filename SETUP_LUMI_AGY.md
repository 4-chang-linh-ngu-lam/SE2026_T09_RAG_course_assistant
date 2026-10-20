# Setup: Codex orchestrator + AGY workers (Windows PowerShell)

## 1. Add these files to your existing local repo

Copy/extract all files in this ZIP into the **repository root** (the folder containing `apps/`, `services/`, `.git/`, and root `AGENTS.md`). The ZIP adds `.agents/skills/lumi-frontend-orchestrator/`, `apps/web/AGENTS.md`, `docs/ai/`, and this README. It **does not replace** the root `AGENTS.md` or any existing source code.

Example repository:
`D:\app\cnpm\SE2026_T09_RAG_course_assistant`

Use the ZIP from its download location (replace the actual path):

```powershell
Set-Location 'D:\app\cnpm\SE2026_T09_RAG_course_assistant'
git branch --show-current
git status --short
# Only if branch frontend1 is available and safe for you to work on:
# git switch frontend1
Expand-Archive -LiteralPath 'C:\path\to\lumi_codex_agy_setup.zip' -DestinationPath .
```

Before extraction, inspect whether your workspace already has `apps/web/AGENTS.md` or `docs/ai` custom changes; don't overwrite collaborators' work. `Expand-Archive` without `-Force` refuses to overwrite existing files.

## 2. Verify local tools and authorization

```powershell
node --version            # >=22.17.0
npm --version
codex --version
agy --version
agy models
agy                      # first interactive login when needed; exit afterward
```

If `agy` is not found despite installation, restart the terminal and confirm `C:\Users\<your-user>\AppData\Local\agy\bin` is on PATH. A `check-environment.ps1` fallback looks for `%LOCALAPPDATA%\agy\bin\agy.exe`.

Required AGY model IDs (not marketing names):
- `gemini-3.8-flash-high`
- `gemini-4-argon-high`

The bridge fails instead of using another model if your account lacks one. Check `agy models`, available quota/plan and login; do not hardcode credentials.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\skills\lumi-frontend-orchestrator\scripts\check-environment.ps1
```

## 3. Select Codex orchestrator reasoning

In Codex interactive UI, select **GPT-6.1 Sol** with **xhigh** when available to your account and client. Use **max** only for especially complex architecture/security decisions. The skill itself **does not change the Codex model**. Codex CLI model and effort identifiers/availability can vary by client/version; check `codex --help` or your model picker before pinning a CLI command. If supported, the typical CLI pattern is:

```powershell
codex -m gpt-6.1-sol -c 'model_reasoning_effort="xhigh"'
```

If your Codex CLI rejects the model slug, choose the available identifier through `/model` rather than guessing or silently downgrading.

## 4. Start with a safe audit (no edits)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\skills\lumi-frontend-orchestrator\scripts\invoke-agy.ps1 -Phase Audit -Worker flash -TaskFile docs\ai\task-sample.md
```

The script checks the current Git branch, lists models, invokes AGY headlessly in plan mode with JSON schema, checks `status`, and stores the machine response privately in `%LOCALAPPDATA%\LumiAgy\logs`. It never commits or pushes. **Inspect `git status` even after read-only calls**.

For a complex second-opinion audit, change `-Worker argon`. After Codex creates an exact-scope implementation task, use `-Phase Implement -Worker flash` for UI. Codex implements business logic; Argon remains read-only review. The implement path uses `--mode=accept-edits` **only for standard file edits**. It does **not** use `--dangerously-skip-permissions`.

## 5. Run actual quality gates

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\.agents\skills\lumi-frontend-orchestrator\scripts\qa-web.ps1
```

This runs `git diff --check`, `npm run check` and a **live** `npm run build`; prerequisites: install `apps/web` packages using `npm ci` if needed. Browser E2E and live Core API verification remain separate and must not be claimed if not run.

## 6. Give Codex this initial instruction

> Use `$lumi-frontend-orchestrator` to coordinate completion of the Lumi frontend on branch `frontend1`. First verify Git, read root/web AGENTS, BUSINESS_RULES and FRONTEND.md, audit current features, routes, and integrations. Delegate bounded read-only audits to AGY Gemini 3.8 Flash High, architectural/API assessment to Gemini 4 Argon High. Then select the highest-impact contract-safe vertical slice, write a task contract with exact editable UI paths, let AGY Flash generate UI while Codex implements the logic and integration, review every diff, run npm checks and live build, and report explicit UI-only/blocked-backend states. Do not change services/backend, invent endpoints, overwrite collaborator changes, commit, push or merge. Do not treat mocked functionality as complete.

## Security and common pitfalls

- Don't pass API keys, `.env.local`, tokens, private data, or user passwords to either model. Never log them.
- Treat AGY headless JSON `SUCCESS` as agent completion, **not** a code quality gate. In headless mode shell-command permission requests may be soft-denied despite status `SUCCESS`.
- Never use `--dangerously-skip-permissions` for your project. Prefer Codex-run tests in the owner terminal and bounded AGY file edit permissions.
- Do not run two AGY writers in the same worktree. For true parallelism, use separate worktrees and let Codex inspect/merge their changes carefully.
- The connected GitHub tool was used to inspect source; this package itself has not been tested against your Windows AGY installation, and no GitHub source files were changed by generating the package.


## Installed and exercised on 20 October 2026

The skill is installed in this repository and in `C:/Users/maihu/.codex/skills/lumi-frontend-orchestrator`. Repo/web instructions refer agents to the same skill. No global model, provider or approval settings were changed.

Use the repository bridge, not the globally installed script: its relative paths resolve this checkout. The bridge now uses `scripts/agy-process.py` to preserve multiline prompts and literal JSX quotes through Windows PowerShell 5, captures native JSON stdout, and rejects empty responses or denied actions even when CLI status says SUCCESS. It cleans its temporary argv file and keeps CLI logs private. UI tasks use file read/edit tools; Codex runs shell quality gates. `-ContextDirectory` grants a task explicit context for design artifacts without changing global settings.

Validated tools: Node22.17.0, npm10.9.2, AGY1.4.2; locally available models gemini-3.8-flash-high and gemini-4-argon-high. UI generation and read-only review have both run through the bridge. Recheck availability on another computer. Current product implementation and limitations are in `apps/web/docs/FRONTEND.md`; the old sample audit remains an example, not a current backlog.
