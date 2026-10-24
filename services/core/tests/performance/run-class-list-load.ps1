[CmdletBinding()]
param(
    [ValidateRange(1, 86400)][int]$DurationSeconds = 600,
    [ValidateRange(0, 3600)][int]$WarmupSeconds = 30,
    [ValidateRange(1, 100)][int]$Users = 100,
    [ValidateRange(0, 3600)][double]$ThinkSeconds = 1,
    [string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$coreRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$fixture = 'lumi-core-load-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$privateDirectory = Join-Path ([IO.Path]::GetTempPath()) $fixture
$resultsDirectory = Join-Path $privateDirectory 'results'
$databaseEnv = Join-Path $privateDirectory 'database.env'
$loadEnv = Join-Path $privateDirectory 'load.env'
$databaseCreated = $false
$networkCreated = $false
$loadExit = 1
if (-not $OutputPath) {
    $OutputPath = Join-Path $coreRoot "test-evidence/$fixture/core-load.json"
}
if (-not [IO.Path]::IsPathRooted($OutputPath)) {
    $OutputPath = Join-Path (Get-Location).Path $OutputPath
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $OutputPath) { throw 'Output already exists; choose a new evidence file.' }
New-Item -ItemType Directory -Path $resultsDirectory -Force | Out-Null

try {
    # Credentials belong only to this disposable server; never use the app .env.
    $bytes = New-Object byte[] 32
    $random = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $random.GetBytes($bytes) } finally { $random.Dispose() }
    $password = [BitConverter]::ToString($bytes).Replace('-', '')
    [IO.File]::WriteAllText($databaseEnv, "POSTGRES_USER=load`nPOSTGRES_DB=load`nPOSTGRES_PASSWORD=$password`n")
    [IO.File]::WriteAllText($loadEnv, "TEST_DATABASE_URL=postgresql+psycopg://load:${password}@${fixture}-db:5432/load`nDATABASE_POOL_SIZE=15`nDATABASE_MAX_OVERFLOW=0`n")

    Write-Host 'Building the load image (application and dependencies on the Linux filesystem)...'
    $buildLog = Join-Path $privateDirectory 'build.log'
    # Windows PowerShell treats native stderr as ErrorRecord; Docker uses stderr
    # for normal build progress. Preserve it privately and check the exit code.
    $ErrorActionPreference = 'Continue'
    & docker build --file (Join-Path $PSScriptRoot 'Dockerfile') --tag $fixture $coreRoot *> $buildLog
    $buildExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    if ($buildExit -ne 0) { throw "Load image build failed; private log: $buildLog" }

    & docker network create $fixture | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated network.' }
    $networkCreated = $true
    # Docker may create a container but fail while starting it. Cleanup must also
    # handle that case, without assuming the successful-start exit code.
    $databaseCreated = $true
    & docker run -d --name "${fixture}-db" --network $fixture --env-file $databaseEnv --health-cmd 'pg_isready -U load -d load' --health-interval 1s --health-retries 40 postgres:16-alpine | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the isolated database.' }
    $healthy = $false
    for ($attempt = 0; $attempt -lt 45; $attempt++) {
        $health = & docker inspect --format '{{.State.Health.Status}}' "${fixture}-db"
        if ($LASTEXITCODE -ne 0) { throw 'Database fixture disappeared.' }
        if ($health -eq 'healthy') { $healthy = $true; break }
        Start-Sleep -Seconds 1
    }
    if (-not $healthy) { throw 'Database fixture did not become ready.' }

    Write-Host "Measuring $Users users for ${DurationSeconds}s after ${WarmupSeconds}s warmup..."
    $loadLog = Join-Path $privateDirectory 'load.log'
    $ErrorActionPreference = 'Continue'
    & docker run --rm --name "${fixture}-client" --network $fixture --env-file $loadEnv --mount "type=bind,source=$resultsDirectory,target=/evidence" $fixture --duration-seconds $DurationSeconds --warmup-seconds $WarmupSeconds --users $Users --think-seconds $ThinkSeconds --output /evidence/core-load.json *> $loadLog
    $loadExit = $LASTEXITCODE
    $ErrorActionPreference = 'Stop'
    $reportPath = Join-Path $resultsDirectory 'core-load.json'
    if (-not (Test-Path -LiteralPath $reportPath)) { throw "Measurement produced no report; private log: $loadLog" }
    $report = Get-Content -Raw -LiteralPath $reportPath | ConvertFrom-Json
    New-Item -ItemType Directory -Path (Split-Path -Parent $OutputPath) -Force | Out-Null
    # CreateNew preserves historical evidence, including concurrent invocations.
    $destination = [IO.File]::Open($OutputPath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write)
    try {
        $reportBytes = [IO.File]::ReadAllBytes($reportPath)
        $destination.Write($reportBytes, 0, $reportBytes.Length)
    } finally { $destination.Dispose() }
    [ordered]@{
        output = $OutputPath
        requests = $report.requests
        backend_p95_ms = $report.backend_p95_ms
        client_p95_ms = $report.client_p95_ms
        client_error_counts = $report.client_error_counts
        success_ratio = $report.success_ratio
        wrong_scope_responses = $report.wrong_scope_responses
        passed_core_thresholds = $report.passed_core_thresholds
        load_exit_code = $loadExit
    } | ConvertTo-Json -Depth 5
} finally {
    # Only exact, invocation-owned resources are removed. Other app containers,
    # images and volumes are never enumerated for deletion.
    if ($fixture -notmatch '^lumi-core-load-[0-9a-f]{12}$') { throw 'Unsafe fixture name.' }
    $ErrorActionPreference = 'Continue'
    if ($networkCreated) {
        $remaining = & docker ps -aq --filter "name=^/${fixture}-client$"
        if ($remaining) { & docker rm -f -v "${fixture}-client" | Out-Null }
    }
    if ($databaseCreated) {
        $actualNetwork = & docker inspect --format '{{.HostConfig.NetworkMode}}' "${fixture}-db" 2>$null
        if ($LASTEXITCODE -eq 0) {
            if ($actualNetwork -eq $fixture) { & docker rm -f -v "${fixture}-db" | Out-Null }
            else { Write-Warning 'Fixture network changed; database cleanup was refused.' }
        }
    }
    if ($networkCreated) { & docker network rm $fixture | Out-Null }
    & docker image rm $fixture 2>$null | Out-Null
    foreach ($secretFile in @($databaseEnv, $loadEnv)) {
        if (Test-Path -LiteralPath $secretFile) { Remove-Item -LiteralPath $secretFile -Force }
    }
}
exit $loadExit
