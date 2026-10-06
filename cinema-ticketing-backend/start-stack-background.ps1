param([switch]$RunServices, [string]$JavaPath)
$ErrorActionPreference = 'Stop'
$taskRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$taskLogs = Join-Path $taskRoot 'target'
New-Item -ItemType Directory -Force -Path $taskLogs | Out-Null

if (!$RunServices) {
    # WMI creates the hidden launcher outside the calling terminal's process job.
    # This keeps services alive when the terminal or an interrupted tool run ends.
    $taskStartup = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $taskShell = (Get-Process -Id $PID).Path
    $taskCommand = '"' + $taskShell + '" -NoProfile -File "' + $PSCommandPath + '" -RunServices'
    if (!$JavaPath) { $JavaPath = if ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin/java.exe' } else { (Get-Command java.exe).Source } }
    $taskCommand += ' -JavaPath "' + $JavaPath + '"'
    $taskResult = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
        CommandLine = $taskCommand; CurrentDirectory = $taskRoot; ProcessStartupInformation = $taskStartup
    }
    if ($taskResult.ReturnValue -ne 0) { throw "Background launch failed: $($taskResult.ReturnValue)" }
    Write-Host "Background launcher PID=$($taskResult.ProcessId); logs: target/stack-startup.log"
    return
}

Start-Transcript -Path (Join-Path $taskLogs 'stack-startup.log') -Force | Out-Null
try {
    if (!(Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue)) {
        $taskJava = if ($JavaPath) { $JavaPath } elseif ($env:JAVA_HOME) { Join-Path $env:JAVA_HOME 'bin/java.exe' } else { (Get-Command java.exe).Source }
        $taskSockets = Join-Path $taskLogs 'sockets'
        New-Item -ItemType Directory -Force -Path $taskSockets | Out-Null
        $taskArguments = @('-Duser.timezone=Asia/Shanghai', "-Djdk.net.unixdomain.tmpdir=$taskSockets", '-jar',
            (Join-Path $taskLogs 'cinema-ticketing-backend-0.0.1-SNAPSHOT.jar'), '--spring.profiles.active=local', '--server.port=8080')
        Start-Process -FilePath $taskJava -ArgumentList $taskArguments -WorkingDirectory $taskRoot -WindowStyle Hidden `
            -RedirectStandardOutput (Join-Path $taskLogs 'memory-backend-stdout.log') `
            -RedirectStandardError (Join-Path $taskLogs 'memory-backend-stderr.log') | Out-Null
    }
    foreach ($taskService in @(@{Name='chroma';Port=8030},@{Name='mcp';Port=8020},@{Name='agent';Port=8000},@{Name='gateway';Port=8010})) {
        if (!(Get-NetTCPConnection -LocalPort $taskService.Port -State Listen -ErrorAction SilentlyContinue)) {
            & (Join-Path $taskRoot 'start-ai-local.ps1') -Service $taskService.Name
        }
    }
    $taskStatePath = Join-Path $taskLogs 'ai-memory-process.json'
    $taskMemoryRunning = $false
    if (Test-Path -LiteralPath $taskStatePath) {
        $taskSaved = Get-Content -LiteralPath $taskStatePath -Raw | ConvertFrom-Json
        $taskExisting = Get-Process -Id $taskSaved.pid -ErrorAction SilentlyContinue
        $taskMemoryRunning = $taskExisting -and $taskExisting.StartTime.ToUniversalTime().Ticks -eq $taskSaved.started
    }
    if (!$taskMemoryRunning) { & (Join-Path $taskRoot 'start-ai-local.ps1') -Service memory }
} finally { Stop-Transcript | Out-Null }
