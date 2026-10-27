[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path

function Find-Agy {
    $found = Get-Command agy -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    $candidate = Join-Path $env:LOCALAPPDATA 'agy\bin\agy.exe'
    if (Test-Path $candidate) { return $candidate }
    throw 'AGY not found. Open a new PowerShell terminal after installation or check %LOCALAPPDATA%\agy\bin.'
}

Push-Location $repoRoot
try {
    $branch = (& git branch --show-current)
    $sha = (& git rev-parse --short HEAD)
    if ($LASTEXITCODE -ne 0) { throw 'Not a Git checkout.' }
    Write-Host "Repo: $repoRoot"
    Write-Host "Branch: $branch"
    Write-Host "HEAD: $sha"
    if ($branch -ne 'frontend1') { Write-Warning 'Expected frontend1. Do not let AGY edit until branch scope is confirmed.' }
    Write-Host "Git status:"
    & git status --short
    if ($LASTEXITCODE -ne 0) { throw 'git status failed.' }

    $nodeVersion = (& node --version)
    if ($LASTEXITCODE -ne 0) { throw 'Node is not available.' }
    $version = [version]($nodeVersion.TrimStart('v').Split('-')[0])
    if ($version -lt [version]'22.17.0') { throw "Node $nodeVersion is too old; need >=22.17.0." }
    Write-Host "Node: $nodeVersion"

    & npm --version
    if ($LASTEXITCODE -ne 0) { throw 'npm is not available.' }
    $codex = Get-Command codex -ErrorAction SilentlyContinue
    if ($codex) { & codex --version } else { Write-Warning 'Codex CLI not found in PATH (the skill may still be used in Codex IDE).' }

    $agyExe = Find-Agy
    Write-Host "AGY executable: $agyExe"
    & $agyExe --version
    if ($LASTEXITCODE -ne 0) { throw 'AGY --version failed.' }
    $models = (& $agyExe models | Out-String)
    if ($LASTEXITCODE -ne 0) { throw 'AGY models failed: login or plan verification may be required. Run agy interactively.' }
    @('gemini-3.8-flash-high', 'gemini-4-argon-high') | ForEach-Object {
        if ($models -notmatch [regex]::Escape($_)) { Write-Warning "Model not found on this account: $_" }
        else { Write-Host "Model available: $_" }
    }
    Write-Host 'Ready for task delegation only after Codex confirms scope and contracts.'
}
finally { Pop-Location }
