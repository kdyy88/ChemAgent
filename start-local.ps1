<#
start-local.ps1

Restricted Windows local launcher for ChemAgent.

Features:
  - Uses root .env as the single env source
  - Uses uv to sync backend dependencies
    - Reuses an existing Redis from REDIS_URL when available
    - Starts a local Redis-compatible server when a Windows binary is available
  - Can skip worker startup
  - Writes process logs into .dev-logs/

Usage:
  .\start-local.ps1
  .\start-local.ps1 -NoWorker
  .\start-local.ps1 -NoRedis
  .\start-local.ps1 -DryRun
#>

[CmdletBinding()]
param(
    [switch]$NoWorker,
    [switch]$NoRedis,
    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) {
    $scriptRoot = (Get-Location).Path
}

$Root = $scriptRoot
$BackendDir = Join-Path $Root 'backend'
$FrontendDir = Join-Path $Root 'frontend'
$EnvFile = Join-Path $Root '.env'
$LogDir = Join-Path $Root '.dev-logs'

function Write-Info([string]$Message) { Write-Host ('[INFO] ' + $Message) -ForegroundColor Cyan }
function Write-Warn([string]$Message) { Write-Host ('[WARN] ' + $Message) -ForegroundColor Yellow }

function Require-Command([string]$Name) {
    $cmd = Get-Command $Name -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw ('Missing command: ' + $Name)
    }
    return $cmd.Source
}

function Test-TcpPort([string]$HostName, [int]$Port, [int]$TimeoutMs = 1000) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect($HostName, $Port, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Wait-TcpPort([string]$HostName, [int]$Port, [string]$Label, [int]$MaxSeconds = 30) {
    for ($i = 0; $i -lt ($MaxSeconds * 2); $i++) {
        if (Test-TcpPort -HostName $HostName -Port $Port) {
            Write-Info ($Label + ' is ready at ' + $HostName + ':' + $Port)
            return $true
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Warn ($Label + ' did not become ready within ' + $MaxSeconds + 's')
    return $false
}

function Load-DotEnv([string]$Path) {
    if (-not (Test-Path $Path)) {
        throw ('Missing env file: ' + $Path + '. Copy .env.example first.')
    }

    $doubleQuote = [char]34
    $singleQuote = [char]39

    foreach ($rawLine in Get-Content -Path $Path -Encoding UTF8) {
        $line = $rawLine.Trim()
        if (-not $line -or $line.StartsWith('#')) {
            continue
        }
        if ($line -notmatch '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            continue
        }

        $name = $matches[1]
        $value = $matches[2].Trim()

        if ($value.Length -ge 2) {
            $firstChar = $value[0]
            $lastChar = $value[$value.Length - 1]
            if (($firstChar -eq $doubleQuote -and $lastChar -eq $doubleQuote) -or ($firstChar -eq $singleQuote -and $lastChar -eq $singleQuote)) {
                $value = $value.Substring(1, $value.Length - 2)
            }
        }

        [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
    }
}

function Get-RedisConfig() {
    $defaultRedisUrl = 'redis://127.0.0.1:6379/0'
    $redisUrl = [System.Environment]::GetEnvironmentVariable('REDIS_URL', 'Process')
    if ([string]::IsNullOrWhiteSpace($redisUrl)) {
        $redisUrl = $defaultRedisUrl
    }

    try {
        $uri = [System.Uri]$redisUrl
    } catch {
        throw ('Invalid REDIS_URL: ' + $redisUrl)
    }

    if ([string]::IsNullOrWhiteSpace($uri.Host)) {
        throw ('REDIS_URL must include a host: ' + $redisUrl)
    }

    $port = if ($uri.IsDefaultPort) { 6379 } else { $uri.Port }
    $hostName = $uri.Host
    $isLoopback = $hostName -eq '127.0.0.1' -or $hostName -eq 'localhost' -or $hostName -eq '::1'

    return [PSCustomObject]@{
        Url = $redisUrl
        HostName = $hostName
        Port = $port
        IsLoopback = $isLoopback
    }
}

function Resolve-RedisLauncher([string]$RootDir, [int]$Port) {
    $configuredPath = [System.Environment]::GetEnvironmentVariable('REDIS_SERVER_PATH', 'Process')
    $candidatePaths = @()
    if (-not [string]::IsNullOrWhiteSpace($configuredPath)) {
        $candidatePaths += $configuredPath.Trim()
    }
    $candidatePaths += @( 
        (Join-Path $RootDir 'tools\redis\redis-server.exe'),
        (Join-Path $RootDir 'tools\redis\valkey-server.exe'),
        (Join-Path $RootDir '.tools\redis\redis-server.exe'),
        (Join-Path $RootDir '.tools\redis\valkey-server.exe'),
        (Join-Path $RootDir 'redis\redis-server.exe'),
        (Join-Path $RootDir 'redis\valkey-server.exe')
    )

    foreach ($candidate in $candidatePaths) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and (Test-Path $candidate)) {
            return [PSCustomObject]@{
                Kind = 'native'
                FilePath = $candidate
                Arguments = @('--port', [string]$Port, '--maxmemory', '128mb', '--maxmemory-policy', 'allkeys-lru', '--save', '', '--appendonly', 'no', '--loglevel', 'notice')
                Description = ('local executable at ' + $candidate)
            }
        }
    }

    $redisCmd = Get-Command 'redis-server' -ErrorAction SilentlyContinue
    if ($redisCmd) {
        return [PSCustomObject]@{
            Kind = 'native'
            FilePath = $redisCmd.Source
            Arguments = @('--port', [string]$Port, '--maxmemory', '128mb', '--maxmemory-policy', 'allkeys-lru', '--save', '', '--appendonly', 'no', '--loglevel', 'notice')
            Description = ('PATH executable at ' + $redisCmd.Source)
        }
    }

    $valkeyCmd = Get-Command 'valkey-server' -ErrorAction SilentlyContinue
    if ($valkeyCmd) {
        return [PSCustomObject]@{
            Kind = 'native'
            FilePath = $valkeyCmd.Source
            Arguments = @('--port', [string]$Port, '--maxmemory', '128mb', '--maxmemory-policy', 'allkeys-lru', '--save', '', '--appendonly', 'no', '--loglevel', 'notice')
            Description = ('PATH executable at ' + $valkeyCmd.Source)
        }
    }

    return $null
}

function Start-LoggedProcess(
    [string]$Name,
    [string]$FilePath,
    [string[]]$Arguments,
    [string]$WorkingDirectory
) {
    $stdout = Join-Path $LogDir ($Name + '.stdout.log')
    $stderr = Join-Path $LogDir ($Name + '.stderr.log')

    if ($DryRun) {
        Write-Info ('[DryRun] ' + $Name + ' => ' + $FilePath + ' ' + ($Arguments -join ' '))
        return $null
    }

    $startArgs = @{
        FilePath = $FilePath
        ArgumentList = $Arguments
        WorkingDirectory = $WorkingDirectory
        RedirectStandardOutput = $stdout
        RedirectStandardError = $stderr
        PassThru = $true
        WindowStyle = 'Hidden'
    }

    $proc = Start-Process @startArgs
    Write-Info ($Name + ' started with PID=' + $proc.Id)
    Write-Info ($Name + ' logs: ' + $stdout + ' / ' + $stderr)
    return $proc
}

Write-Info 'Starting local launcher for restricted Windows environment'

if (-not (Test-Path $BackendDir)) {
    throw ('Missing backend directory: ' + $BackendDir)
}
if (-not (Test-Path $FrontendDir)) {
    throw ('Missing frontend directory: ' + $FrontendDir)
}

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Load-DotEnv -Path $EnvFile

$uv = Require-Command 'uv'
$pnpmCmd = Get-Command 'pnpm' -ErrorAction SilentlyContinue
$npmCmd = Get-Command 'npm' -ErrorAction SilentlyContinue
$redisConfig = Get-RedisConfig
$redisLauncher = Resolve-RedisLauncher -RootDir $Root -Port $redisConfig.Port

if (-not $pnpmCmd -and -not $npmCmd) {
    throw 'Missing pnpm and npm; cannot start frontend'
}

Write-Info 'Syncing backend dependencies with uv sync'
Push-Location $BackendDir
try {
    if ($DryRun) {
        Write-Info '[DryRun] uv sync'
    } else {
        try {
            & $uv sync
        } catch {
            Write-Warn 'uv sync failed; trying a minimal fallback dependency set'
            & $uv venv .venv
            $py = Join-Path $BackendDir '.venv\Scripts\python.exe'
            & $uv pip install --python $py fastapi uvicorn python-dotenv python-multipart httpx arq 'redis[hiredis]' langgraph langgraph-checkpoint-sqlite langchain-core langchain-openai openbabel-wheel tavily-python --no-cache-dir
        }
    }
} finally {
    Pop-Location
}

$BackendPython = Join-Path $BackendDir '.venv\Scripts\python.exe'
if (-not (Test-Path $BackendPython) -and -not $DryRun) {
    throw ('Backend virtual environment was not created: ' + $BackendPython)
}

$startWorker = -not $NoWorker
$redisReady = $false
$redisSummary = $redisConfig.HostName + ':' + $redisConfig.Port

if ($NoRedis) {
    Write-Info 'Skipping Redis startup due to -NoRedis'
    $redisReady = Test-TcpPort -HostName $redisConfig.HostName -Port $redisConfig.Port
    if (-not $redisReady) {
        Write-Warn ('Configured Redis is not reachable at ' + $redisSummary + '; worker will be disabled')
        $startWorker = $false
    }
}
elseif (Test-TcpPort -HostName $redisConfig.HostName -Port $redisConfig.Port) {
    Write-Info ('Reusing existing Redis at ' + $redisConfig.Url)
    $redisReady = $true
}
elseif ($redisConfig.IsLoopback -and $redisLauncher) {
    Write-Info ('Starting local Redis via ' + $redisLauncher.Description)
    Start-LoggedProcess -Name 'redis' -FilePath $redisLauncher.FilePath -Arguments $redisLauncher.Arguments -WorkingDirectory $Root | Out-Null
    $redisReady = if ($DryRun) { $true } else { Wait-TcpPort -HostName $redisConfig.HostName -Port $redisConfig.Port -Label 'Redis' -MaxSeconds 20 }
}
elseif (-not $redisConfig.IsLoopback) {
    Write-Warn ('Configured REDIS_URL points to ' + $redisSummary + ' but it is not reachable; worker will be disabled')
    $startWorker = $false
}
else {
    Write-Warn ('Redis launcher not found for ' + $redisSummary + '. Set REDIS_SERVER_PATH to a portable redis-server.exe or valkey-server.exe, add one to PATH, or provide a reachable REDIS_URL; worker will be disabled')
    $startWorker = $false
}

if (-not $redisReady -and $startWorker) {
    Write-Warn 'Redis is not ready; worker will not start'
    $startWorker = $false
}

Write-Info 'Starting backend'
if ($DryRun) {
    Write-Info ('[DryRun] ' + $BackendPython + ' -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000')
}
else {
    Start-LoggedProcess -Name 'backend' -FilePath $BackendPython -Arguments @('-m', 'uvicorn', 'app.main:app', '--reload', '--host', '127.0.0.1', '--port', '8000', '--log-level', 'info') -WorkingDirectory $BackendDir | Out-Null
    [void](Wait-TcpPort -HostName '127.0.0.1' -Port 8000 -Label 'Backend' -MaxSeconds 30)
}

if ($startWorker) {
    Write-Info 'Starting ARQ worker'
    if ($DryRun) {
        Write-Info ('[DryRun] ' + $BackendPython + ' -m arq app.worker.WorkerSettings')
    }
    else {
        Start-LoggedProcess -Name 'worker' -FilePath $BackendPython -Arguments @('-m', 'arq', 'app.worker.WorkerSettings') -WorkingDirectory $BackendDir | Out-Null
    }
}
else {
    Write-Warn 'Worker not started'
}

Write-Info 'Preparing frontend dependencies'
Push-Location $FrontendDir
try {
    if ($pnpmCmd) {
        if ($DryRun) {
            Write-Info '[DryRun] pnpm install'
        }
        else {
            & $pnpmCmd.Source install
        }
        $frontendFile = $pnpmCmd.Source
        $frontendArgs = @('dev')
    }
    else {
        Write-Warn 'pnpm not found; using npm fallback'
        if ($DryRun) {
            Write-Info '[DryRun] npm install'
        }
        else {
            & $npmCmd.Source install
        }
        $frontendFile = $npmCmd.Source
        $frontendArgs = @('run', 'dev')
    }
}
finally {
    Pop-Location
}

if ($DryRun) {
    Write-Info ('[DryRun] ' + $frontendFile + ' ' + ($frontendArgs -join ' '))
}
else {
    Start-LoggedProcess -Name 'frontend' -FilePath $frontendFile -Arguments $frontendArgs -WorkingDirectory $FrontendDir | Out-Null
    [void](Wait-TcpPort -HostName '127.0.0.1' -Port 3000 -Label 'Frontend' -MaxSeconds 60)
}

Write-Host ''
Write-Host '=== Local launch summary ===' -ForegroundColor Green
Write-Host 'App:    http://localhost:3000' -ForegroundColor Cyan
Write-Host 'API:    http://localhost:8000/docs' -ForegroundColor Cyan
if ($redisReady) {
    Write-Host ('Redis:  ' + $redisConfig.Url) -ForegroundColor Cyan
}
else {
    Write-Host ('Redis:  not started or not reachable (' + $redisConfig.Url + ')') -ForegroundColor Yellow
}
if ($startWorker) {
    Write-Host 'Worker: running' -ForegroundColor Green
}
else {
    Write-Host 'Worker: off' -ForegroundColor Yellow
}
Write-Host ('Logs:   ' + $LogDir) -ForegroundColor Cyan
Write-Host ''
Write-Info 'Command dispatch completed'
