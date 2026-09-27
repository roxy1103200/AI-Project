param([string]$InternalToken = $env:AI_INTERNAL_TOKEN,
      [ValidateSet('all','agent','gateway')][string]$Service = 'all')
$ErrorActionPreference = 'Stop'
$aiDirectory = Join-Path $PSScriptRoot 'cinema-ai'
$gatewayDirectory = Join-Path $PSScriptRoot 'cinema-ai-gateway'
$pythonPath = Join-Path $aiDirectory '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw '请先按 docs/dify-agent-setup.md 创建 cinema-ai/.venv 并安装依赖。'
}
if (!$InternalToken) { $InternalToken = 'local-internal-token' }
$env:AI_INTERNAL_TOKEN = $InternalToken
if (!$env:JAVA_API_URL) { $env:JAVA_API_URL = 'http://127.0.0.1:8080' }
if (!$env:AGENT_API_URL) { $env:AGENT_API_URL = 'http://127.0.0.1:8000' }
if (!$env:DIFY_API_KEY_FILE) { $env:DIFY_API_KEY_FILE = Join-Path (Split-Path $PSScriptRoot -Parent) 'API/dify.txt' }
if (!$env:QWEN_API_KEY_FILE) { $env:QWEN_API_KEY_FILE = Join-Path (Split-Path $PSScriptRoot -Parent) 'API/qwen.txt' }
$logDirectory = Join-Path $PSScriptRoot 'target'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$selectedServices = @(@{ Name = 'agent'; Port = 8000; Directory = $aiDirectory }, @{ Name = 'gateway'; Port = 8010; Directory = $gatewayDirectory })
if ($Service -ne 'all') { $selectedServices = @($selectedServices | Where-Object { $_.Name -eq $Service }) }
foreach ($aiService in $selectedServices) {
    if (Get-NetTCPConnection -LocalPort $aiService.Port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $($aiService.Port) 已被占用；请检查并停止旧服务后重试。"
    }
}
foreach ($aiService in $selectedServices) {
    $arguments = @('-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', $aiService.Port)
    if ($aiService.Name -eq 'gateway') {
        $workerSetting = $env:AI_GATEWAY_WORKERS
        $gatewayEnvFile = Join-Path $gatewayDirectory '.env'
        if (!$workerSetting -and (Test-Path -LiteralPath $gatewayEnvFile)) {
            foreach ($line in Get-Content -LiteralPath $gatewayEnvFile) {
                if ($line -match '^\s*AI_GATEWAY_WORKERS\s*=\s*["'']?(\d+)["'']?\s*(?:#.*)?$') { $workerSetting = $Matches[1] }
            }
        }
        $workers = if ($workerSetting) { [int]$workerSetting } else { 2 }
        if ($workers -lt 1 -or $workers -gt 8) { throw 'AI_GATEWAY_WORKERS 必须为 1～8。' }
        $arguments += @('--workers', $workers)
    }
    if (Test-Path -LiteralPath (Join-Path $aiService.Directory '.env')) {
        $arguments += @('--env-file', (Join-Path $aiService.Directory '.env'))
    }
    $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments `
        -WorkingDirectory $aiService.Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "ai-$($aiService.Name)-stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "ai-$($aiService.Name)-stderr.log")
    Write-Host "$($aiService.Name): PID=$($process.Id), port=$($aiService.Port)"
}

