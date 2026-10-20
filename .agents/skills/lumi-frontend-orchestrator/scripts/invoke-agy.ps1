[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('Audit', 'Implement', 'Review')]
    [string] $Phase,

    [Parameter(Mandatory = $true)]
    [ValidateSet('flash', 'argon')]
    [string] $Worker,

    [Parameter(Mandatory = $true)]
    [string] $TaskFile,

    [string[]] $ContextDirectory = @(),

    [ValidateRange(5, 60)]
    [int] $TimeoutMinutes = 20
)

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$webRoot = Join-Path $repoRoot 'apps\web'
$model = switch ($Worker) {
    flash { 'gemini-3.8-flash-high' }
    argon { 'gemini-4-argon-high' }
}

function Find-Agy {
    $found = Get-Command agy -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidate = Join-Path $env:LOCALAPPDATA 'agy\bin\agy.exe'
    if (Test-Path $candidate) { return $candidate }
    throw 'agy not found. Restart terminal or repair installation.'
}

$agyExe = Find-Agy
$inputPath = if ([System.IO.Path]::IsPathRooted($TaskFile)) { [System.IO.Path]::GetFullPath($TaskFile) } else { [System.IO.Path]::GetFullPath((Join-Path $repoRoot $TaskFile)) }
if (-not $inputPath.StartsWith($repoRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw 'TaskFile must be inside the repository.'
}
if (-not (Test-Path -Path $inputPath -PathType Leaf)) { throw "Task file not found: $inputPath" }
$taskText = Get-Content -LiteralPath $inputPath -Raw -Encoding UTF8
if ([string]::IsNullOrWhiteSpace($taskText)) { throw 'Task file is empty.' }

$phaseDirective = switch ($Phase) {
    Audit { 'READ-ONLY AUDIT. Do not write any file. Return evidence and findings with exact paths.' }
    Implement { 'IMPLEMENT ONLY THE EXPLICIT EDITABLE SCOPE in the task contract. You may edit within this scope, but cannot commit, push, change branches, or run destructive Git commands. If any integration contract is unavailable, leave an honest unavailable UI and report the blocker.' }
    Review { 'READ-ONLY REVIEW. Inspect code and Git diff, not modify files. Highlight contract deviations and bugs; report evidence with exact paths.' }
}
$prompt = @"
You are an AGY worker for Lumi frontend, supervised by Codex. $phaseDirective
Read the repository root AGENTS.md, apps/web/AGENTS.md, and .agents/skills/lumi-frontend-orchestrator/SKILL.md and obey higher-priority business rules. AGY owns UI; Codex owns business logic and integration. This UI task permits file reading/editing tools ONLY. Never invoke RunCommand/command/terminal/shell, even for pwd, listing, reading, Git or tests. Codex already handles environment, Git and checks. Use explicit absolute paths with file tools.
Project scope: apps/web only. Never modify services/, docs/architect/, root AGENTS.md, .env files, credentials or unrelated files.
Do not execute git commit, push, checkout, reset, clean, rebase, merge or force operations. Do not invent backend API contracts or silently switch to mock data.
Keep the work limited; report exactly which files you changed (if any), tests actually executed, unresolved risks, and blockers.

Task contract:
$taskText
"@

Push-Location $repoRoot
try {
    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot identify Git branch.' }
    if ($branch -ne 'frontend1') { throw "Current branch is '$branch', expected 'frontend1'. Switch or update configuration explicitly." }
    $before = (& git status --porcelain=v1 | Out-String)
    $head = (& git rev-parse HEAD).Trim()
    if ($before.Trim()) {
        Write-Warning 'Worktree has pre-existing changes. Review them before trusting AGY modifications:'
        Write-Host $before
    }
    $models = (& $agyExe models | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'Cannot list AGY models; authenticate with interactive agy first.' }
    if ($models -notmatch [regex]::Escape($model)) { throw "Required model '$model' not available in agy models. No silent fallback." }

    $mode = if ($Phase -eq 'Implement') { '--mode=accept-edits' } else { '--mode=plan' }
    $argsList = @('-p', $prompt, '--model', $model, '--output-format', 'json', '--print-timeout', "${TimeoutMinutes}m", $mode)
    foreach ($contextPath in $ContextDirectory) {
        $resolvedContext = (Resolve-Path -LiteralPath $contextPath).Path
        if (-not (Test-Path -LiteralPath $resolvedContext -PathType Container)) { throw "Context directory not found: $contextPath" }
        $argsList += @('--add-dir', $resolvedContext)
    }
    if ($Phase -ne 'Implement') {
        $schema = Join-Path $PSScriptRoot '..\schemas\review.schema.json'
        $argsList += @('--json-schema', $schema)
    }

    Write-Host "AGY $Worker ($model), phase=$Phase, branch=$branch, HEAD=$head"
    Write-Host 'Running one scoped task. AGY cannot commit/push; Codex must inspect the diff and run gates.'
    # Windows PowerShell 5 can split literal JSX quotes when marshalling a
    # multiline native argument. Python's subprocess list preserves each argv.
    $requestPath = Join-Path $env:TEMP ("lumi-agy-argv-" + [Guid]::NewGuid().ToString('N') + '.json')
    try {
        @{ executable = $agyExe; arguments = $argsList } | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $requestPath -Encoding UTF8
        $launcher = Join-Path $PSScriptRoot 'agy-process.py'
        $raw = & python -X utf8 $launcher $requestPath | Out-String
        $exit = $LASTEXITCODE
    }
    finally { if (Test-Path -LiteralPath $requestPath) { Remove-Item -LiteralPath $requestPath } }
    if ([string]::IsNullOrWhiteSpace($raw)) { throw "AGY returned empty stdout (exit $exit). Check stderr and auth." }
    try { $result = $raw | ConvertFrom-Json -ErrorAction Stop }
    catch { throw "AGY did not return valid JSON (exit $exit). Inspect CLI compatibility: $($_.Exception.Message)" }

    $logBase = if ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'LumiAgy\logs' } else { Join-Path $env:TEMP 'LumiAgy\logs' }
    New-Item -ItemType Directory -Path $logBase -Force | Out-Null
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $logPath = Join-Path $logBase "$stamp-$Phase-$Worker.json"
    $raw | Set-Content -LiteralPath $logPath -Encoding UTF8
    Write-Host "Private AGY run log: $logPath"
    Write-Host "Status: $($result.status); CLI exit: $exit"
    if ($result.structured_output) { $result.structured_output | ConvertTo-Json -Depth 30 | Write-Output }
    elseif ($result.response) { Write-Output $result.response }
    if ($exit -ne 0 -or $result.status -ne 'SUCCESS') { throw "AGY task failed with status '$($result.status)' / exit $exit. Error: $($result.error)" }

    if ($result.denied_actions -and @($result.denied_actions).Count -gt 0) { throw 'AGY reported denied actions; this run is not accepted. Do not change permission settings.' }
    if (-not $result.response -and -not $result.structured_output) { throw 'AGY returned no implementation or review response; do not treat terminal SUCCESS as acceptance.' }

    $after = (& git status --porcelain=v1 | Out-String)
    if ($Phase -ne 'Implement' -and $after -ne $before) {
        Write-Warning 'Read-only run changed repository state; investigate before proceeding.'
    }
    Write-Host 'Changed files (relative to pre-run status must be reviewed manually):'
    & git status --short
    Write-Host 'Codex next: inspect git diff -- apps/web, run npm run check + npm run build in apps/web.'
}
finally { Pop-Location }
