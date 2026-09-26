param(
    [string]$Profile = 'local',
    [int]$Port = 8080
)

$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    & mvn package -DskipTests
    if ($LASTEXITCODE -ne 0) {
        throw '后端构建失败，未启动服务。'
    }
    $jarPath = Join-Path $PSScriptRoot 'target/cinema-ticketing-backend-0.0.1-SNAPSHOT.jar'
    $imagePath = Join-Path (Split-Path $PSScriptRoot -Parent) '图片'
    $socketPath = Join-Path $PSScriptRoot 'target/sockets'
    New-Item -ItemType Directory -Path $socketPath -Force | Out-Null
    Write-Host '使用本次构建启动后端；重新加载新增接口需要先停止旧服务。'
    & java -Duser.timezone=Asia/Shanghai "-Djdk.net.unixdomain.tmpdir=$socketPath" -jar $jarPath "--spring.profiles.active=$Profile" "--server.port=$Port" "--media.movie-image-directory=$imagePath"
    if ($LASTEXITCODE -ne 0) {
        throw '后端启动或运行失败，请检查端口占用和基础设施连接。'
    }
} finally {
    Pop-Location
}
