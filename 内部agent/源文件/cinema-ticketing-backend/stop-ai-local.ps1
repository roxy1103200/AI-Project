param([ValidateSet('all','agent','gateway')][string]$Service = 'all')
$ErrorActionPreference = 'Stop'
$projectPath = [System.IO.Path]::GetFullPath($PSScriptRoot)
$ports = if ($Service -eq 'agent') { @(8000) } elseif ($Service -eq 'gateway') { @(8010) } else { @(8000,8010) }
$processes = @(Get-CimInstance Win32_Process)
$targets = [System.Collections.Generic.HashSet[int]]::new()
$ordered = [System.Collections.Generic.List[int]]::new()
function Add-ServiceTree([int]$processId) {
    if (!$targets.Add($processId)) { return }
    foreach ($child in $processes | Where-Object { $_.ParentProcessId -eq $processId }) {
        Add-ServiceTree ([int]$child.ProcessId)
    }
    $ordered.Add($processId)
}
foreach ($servicePort in $ports) {
    $roots = @($processes | Where-Object {
        $_.CommandLine -and $_.CommandLine.Contains($projectPath) -and
        $_.CommandLine -like '*uvicorn app.main:app*' -and $_.CommandLine -match "--port\s+$servicePort(?:\s|$)"
    })
    if (!$roots.Count -and (Get-NetTCPConnection -LocalPort $servicePort -State Listen -ErrorAction SilentlyContinue)) {
        throw "端口 $servicePort 的进程不属于已确认的项目 AI 服务，未停止。"
    }
    foreach ($root in $roots) { Add-ServiceTree ([int]$root.ProcessId) }
}
$stopOrder = $ordered.ToArray()
[Array]::Reverse($stopOrder)
# Stop supervisors before workers so they cannot respawn children during cleanup.
foreach ($processId in $stopOrder) {
    $before = $processes | Where-Object { $_.ProcessId -eq $processId } | Select-Object -First 1
    $current = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
    if ($current -and $before -and $current.CommandLine -eq $before.CommandLine -and $current.ParentProcessId -eq $before.ParentProcessId -and $current.CreationDate -eq $before.CreationDate) {
        # Native termination also handles Python launchers where Stop-Process can fail on Windows.
        $terminationOutput = & taskkill.exe /PID $processId /F 2>&1
        if ($LASTEXITCODE -ne 0) {
            $remaining = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction SilentlyContinue
            if ($remaining -and $remaining.CreationDate -eq $before.CreationDate) {
                throw "无法停止已确认的项目 AI 进程 $processId。"
            }
        }
    }
}
Write-Host "已停止 $Service 项目 AI 服务的已确认进程。"
