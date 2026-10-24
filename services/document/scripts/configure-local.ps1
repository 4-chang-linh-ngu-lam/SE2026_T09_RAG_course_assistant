param([switch]$Start, [switch]$SkipBuild)
$ErrorActionPreference = 'Stop'
$documentRepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../../..'))
$documentRootEnv = Join-Path $documentRepoRoot '.env'
$documentWebEnv = Join-Path $documentRepoRoot 'apps/web/.env.local'
if (-not (Test-Path -LiteralPath $documentRootEnv)) { throw 'Configure the existing Core .env before adding Document.' }

function Read-LocalValue([string]$Text, [string]$Name) {
    $documentMatch = [regex]::Match($Text, '(?m)^' + [regex]::Escape($Name) + '=(.*)$')
    if (-not $documentMatch.Success) { return '' }
    $documentValue = $documentMatch.Groups[1].Value.Trim()
    if ($documentValue.Length -ge 2 -and (($documentValue.StartsWith('"') -and $documentValue.EndsWith('"')) -or ($documentValue.StartsWith("'") -and $documentValue.EndsWith("'")))) {
        return $documentValue.Substring(1, $documentValue.Length - 2)
    }
    return $documentValue
}
function Set-LocalValue([string]$Text, [string]$Name, [string]$Value) {
    if ($Value.Contains("`n") -or $Value.Contains("`r")) { throw 'Invalid environment value.' }
    $documentPattern = '(?m)^' + [regex]::Escape($Name) + '=.*$'
    $documentReplacement = $Name + '=' + $Value
    if ([regex]::IsMatch($Text, $documentPattern)) { return [regex]::Replace($Text, $documentPattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($documentMatch) $documentReplacement }) }
    return $Text.TrimEnd() + "`n" + $documentReplacement + "`n"
}
function New-LocalSecret {
    $documentBytes = New-Object byte[] 32
    $documentRandom = [Security.Cryptography.RandomNumberGenerator]::Create()
    try { $documentRandom.GetBytes($documentBytes) } finally { $documentRandom.Dispose() }
    return [BitConverter]::ToString($documentBytes).Replace('-', '').ToLowerInvariant()
}

$documentRootText = [IO.File]::ReadAllText($documentRootEnv)
$documentUrl = Read-LocalValue $documentRootText 'DOCUMENT_DATABASE_URL'
if (-not $documentUrl) {
    $documentCoreUrl = Read-LocalValue $documentRootText 'DATABASE_URL'
    if (-not $documentCoreUrl) {
        $documentPgUser = Read-LocalValue $documentRootText 'POSTGRES_USER'
        $documentPgPassword = Read-LocalValue $documentRootText 'POSTGRES_PASSWORD'
        $documentPgDatabase = Read-LocalValue $documentRootText 'POSTGRES_DB'
        if (-not $documentPgPassword) { throw 'Core database credentials are not configured.' }
        if (-not $documentPgUser) { $documentPgUser = 'rag_course' }
        if (-not $documentPgDatabase) { $documentPgDatabase = 'rag_course' }
        $documentCoreUrl = 'postgresql+psycopg://' + [Uri]::EscapeDataString($documentPgUser) + ':' + [Uri]::EscapeDataString($documentPgPassword) + '@db:5432/' + [Uri]::EscapeDataString($documentPgDatabase)
    }
    try { $documentCoreUri = [Uri]$documentCoreUrl; if (-not $documentCoreUri.IsAbsoluteUri -or -not $documentCoreUri.Host -or $documentCoreUri.AbsolutePath -eq '/') { throw 'Invalid URL' } }
    catch { throw 'DATABASE_URL is invalid; inspect the local environment without sharing its value.' }
    $documentPgPort = if ($documentCoreUri.Port -gt 0) { $documentCoreUri.Port } else { 5432 }
    $documentUrl = 'postgresql+psycopg://lumi_document:' + (New-LocalSecret) + '@' + $documentCoreUri.Host + ':' + $documentPgPort + $documentCoreUri.AbsolutePath + $documentCoreUri.Query
    $documentRootText = Set-LocalValue $documentRootText 'DOCUMENT_DATABASE_URL' $documentUrl
}
$documentSeenKeys = @{}
foreach ($documentKeyName in @('SECRET_KEY','INTERNAL_SERVICE_SECRET','CORE_PROXY_SECRET','DOCUMENT_EVENTS_SERVICE_SECRET','DOCUMENT_INTERNAL_SERVICE_SECRET','DOCUMENT_EVENT_READER_SECRET')) {
    $documentKeyValue = Read-LocalValue $documentRootText $documentKeyName
    if (-not $documentKeyValue -and $documentKeyName.StartsWith('DOCUMENT_')) {
        $documentKeyValue = New-LocalSecret
        $documentRootText = Set-LocalValue $documentRootText $documentKeyName $documentKeyValue
    }
    if (-not $documentKeyValue -or $documentKeyValue.Length -lt 32) { throw "Configure $documentKeyName with a distinct 32+ character value." }
    if ($documentSeenKeys.ContainsKey($documentKeyValue)) { throw 'Service, proxy and signing credentials must be distinct.' }
    $documentSeenKeys[$documentKeyValue] = $true
}
$documentPortText = Read-LocalValue $documentRootText 'DOCUMENT_PORT'
if (-not $documentPortText) { $documentPortText = '8200' }
if ($documentPortText -notmatch '^\d+$' -or [int]$documentPortText -lt 1 -or [int]$documentPortText -gt 65535) { throw 'Invalid DOCUMENT_PORT.' }
$documentWebText = if (Test-Path -LiteralPath $documentWebEnv) { [IO.File]::ReadAllText($documentWebEnv) } else { '' }
$documentWebText = Set-LocalValue $documentWebText 'DOCUMENT_API_URL' ('http://127.0.0.1:' + $documentPortText)
[IO.File]::WriteAllText($documentRootEnv, $documentRootText, (New-Object Text.UTF8Encoding $false))
[IO.File]::WriteAllText($documentWebEnv, $documentWebText, (New-Object Text.UTF8Encoding $false))
Write-Output 'Document local configuration prepared. Private values were not printed.'

if ($Start) {
    Push-Location $documentRepoRoot
    try {
        $documentComposeArgs = @('compose','--profile','document','up','-d')
        if (-not $SkipBuild) { $documentComposeArgs += '--build' }
        $documentComposeArgs += @('core','notification-worker','document','document-worker')
        $ErrorActionPreference = 'Continue'
        & docker @documentComposeArgs
        $documentStartExit = $LASTEXITCODE
        $ErrorActionPreference = 'Stop'
        if ($documentStartExit -ne 0) { throw 'Document startup failed; inspect local Docker logs.' }
    } finally { Pop-Location }
}
