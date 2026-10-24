[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '../../../..')).Path
$webRoot = Join-Path $repoRoot 'apps\web'
$oldMode = [Environment]::GetEnvironmentVariable('NEXT_PUBLIC_DATA_MODE', 'Process')

function Invoke-Gate([string]$Label, [scriptblock]$Command) {
    Write-Host "=== $Label ==="
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Label failed with exit code $LASTEXITCODE" }
}

try {
    Push-Location $repoRoot
    try {
        Invoke-Gate 'git diff --check' { git diff --check }
        Write-Host 'Review scope manually: git diff --stat; git status --short'
        & git diff --stat
        & git status --short
    }
    finally { Pop-Location }

    Push-Location $webRoot
    try {
        $env:NEXT_PUBLIC_DATA_MODE = 'live'
        Invoke-Gate 'npm run check' { npm run check }
        Invoke-Gate 'npm run build (LIVE production)' { npm run build }
        Write-Host 'Quality gates passed. Still requires browser UX and live backend verification where applicable.'
    }
    finally { Pop-Location }
}
finally { [Environment]::SetEnvironmentVariable('NEXT_PUBLIC_DATA_MODE', $oldMode, 'Process') }
