param([string]$InternalToken = $env:AI_INTERNAL_TOKEN,
      [ValidateSet('all','mcp','agent','gateway','chroma','memory')][string]$Service = 'all')
$ErrorActionPreference = 'Stop'
$aiDirectory = Join-Path $PSScriptRoot 'cinema-ai'
$gatewayDirectory = Join-Path $PSScriptRoot 'cinema-ai-gateway'
$pythonPath = Join-Path $aiDirectory '.venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    throw '请先按 docs/dify-agent-setup.md 创建 cinema-ai/.venv 并安装依赖。'
}
# 不预先设置默认环境值，否则会覆盖 uvicorn --env-file 中的实际配置。
# 各服务自身提供本地默认地址和密钥文件路径；显式传参/已有环境变量仍优先。
if ($InternalToken) { $env:AI_INTERNAL_TOKEN = $InternalToken }
$logDirectory = Join-Path $PSScriptRoot 'target'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$selectedServices = @(
    @{ Name = 'chroma'; Port = 8030; Directory = $aiDirectory; Module = 'app.memory_runtime' },
    @{ Name = 'mcp'; Port = 8020; Directory = $aiDirectory; Module = 'app.mcp_server:app' },
    @{ Name = 'agent'; Port = 8000; Directory = $aiDirectory; Module = 'app.main:app' },
    @{ Name = 'gateway'; Port = 8010; Directory = $gatewayDirectory; Module = 'app.main:app' },
    @{ Name = 'memory'; Port = $null; Directory = $aiDirectory; Module = 'app.memory_runtime' }
)
if ($Service -ne 'all') { $selectedServices = @($selectedServices | Where-Object { $_.Name -eq $Service }) }
foreach ($aiService in $selectedServices) {
    if ($aiService.Name -eq 'memory') {
        $statePath = Join-Path $logDirectory 'ai-memory-process.json'
        if (Test-Path -LiteralPath $statePath) {
            $savedProcess = Get-Content -Raw -LiteralPath $statePath | ConvertFrom-Json
            $existingProcess = Get-Process -Id $savedProcess.pid -ErrorAction SilentlyContinue
            if ($existingProcess -and $existingProcess.StartTime.ToUniversalTime().Ticks -eq $savedProcess.started) {
                throw '索引工作进程已启动；请先使用 stop-ai-local.ps1 -Service memory。'
            }
        }
    }
    if ($aiService.Port -and (Get-NetTCPConnection -LocalPort $aiService.Port -State Listen -ErrorAction SilentlyContinue)) {
        throw "端口 $($aiService.Port) 已被占用；请检查并停止旧服务后重试。"
    }
}
foreach ($aiService in $selectedServices) {
    $arguments = @('-m', 'uvicorn', $aiService.Module, '--app-dir', $aiService.Directory, '--host', '127.0.0.1', '--port', $aiService.Port)
    if ($aiService.Name -in @('chroma','memory')) {
        $arguments = @('-m', 'app.memory_runtime', '--service', $aiService.Name, '--project-root', $PSScriptRoot)
    }
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
    if ($aiService.Name -notin @('chroma','memory') -and (Test-Path -LiteralPath (Join-Path $aiService.Directory '.env'))) {
        $arguments += @('--env-file', (Join-Path $aiService.Directory '.env'))
    }
    $process = Start-Process -FilePath $pythonPath -ArgumentList $arguments `
        -WorkingDirectory $aiService.Directory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $logDirectory "ai-$($aiService.Name)-stdout.log") `
        -RedirectStandardError (Join-Path $logDirectory "ai-$($aiService.Name)-stderr.log")
    if ($aiService.Name -eq 'memory') {
        @{ pid = $process.Id; started = $process.StartTime.ToUniversalTime().Ticks } | ConvertTo-Json |
            Set-Content -LiteralPath (Join-Path $logDirectory 'ai-memory-process.json') -Encoding UTF8
    }
    if ($aiService.Name -eq 'mcp') {
        $ready = $false
        $deadline = [DateTime]::UtcNow.AddSeconds(15)
        while ([DateTime]::UtcNow -lt $deadline) {
            if ($process.HasExited) { break }
            try {
                $health = Invoke-RestMethod -Uri "http://127.0.0.1:$($aiService.Port)/health" -TimeoutSec 1
                if ($health.status -eq 'UP' -and $health.service -eq 'cinema-mcp') { $ready = $true; break }
            } catch { }
            Start-Sleep -Milliseconds 200
        }
        if (!$ready) { throw "MCP 未成功启动，请检查 target/ai-mcp-stderr.log；尚未启动后续 Agent/网关。" }
    }
    Write-Host "$($aiService.Name): PID=$($process.Id), port=$($aiService.Port)"
}
if ($Service -eq 'agent') { Write-Host 'Agent 查询需要 MCP 服务：请先启动 -Service mcp，或配置 CINEMA_MCP_URL 指向已有服务。' }

