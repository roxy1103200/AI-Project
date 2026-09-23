# 固定虚拟机的 IP：在 VMware 的 DHCP 里给 MAC 加一条地址保留
#
# 为什么用 DHCP 保留而不是在 guest 里写死静态 IP：
#   vmnet8 的地址池是 192.168.100.128-254，.133 就在池子里。如果 guest 里写静态 .133，
#   这台虚拟机长时间关机、租约过期后，DHCP 可能把 .133 分给别的虚拟机，造成 IP 冲突
#   —— 那比 IP 会变更糟。保留地址仍然走 DHCP，既固定了地址又不会脱离池子，
#   网关和 DNS 也照常下发。
#
# 用法：以管理员身份运行
#   Start-Process powershell -Verb RunAs -ArgumentList '-NoExit','-ExecutionPolicy','Bypass','-File','E:\development\AI-Project\pin-vm-ip.ps1'

$ErrorActionPreference = 'Stop'

$conf = 'C:\ProgramData\VMware\vmnetdhcp.conf'
$mac  = '00:0c:29:1f:a2:3e'   # 虚拟机 ens33 的 MAC，已由 DHCP 租约和 ARP 表双重确认
$ip   = '192.168.100.133'
$name = 'cinema-vm'

# --- 0. 权限检查 ---
$principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host '[X] 需要管理员权限。' -ForegroundColor Red
    exit 1
}
Write-Host '[OK] 管理员权限已确认'

if (-not (Test-Path $conf)) {
    Write-Host "[X] 找不到 $conf" -ForegroundColor Red
    exit 1
}

# --- 1. 备份 ---
$backup = "$conf.bak-$(Get-Date -Format 'yyyyMMdd-HHmmss')"
Copy-Item $conf $backup -Force
Write-Host "[OK] 已备份 -> $backup"

# --- 2. 幂等检查：该 MAC 是否已有保留 ---
$text = [System.IO.File]::ReadAllText($conf)
if ($text -match [regex]::Escape($mac)) {
    Write-Host '[--] 该 MAC 已经有保留条目，不重复添加' -ForegroundColor Yellow
} else {
    # 插到 subnet 192.168.100.0 块的闭合括号之前。
    # 必须放在块内：host 段写在 subnet 之外就拿不到该子网的 routers / domain-name-servers 选项，
    # 虚拟机会失去默认网关。
    $subnet = [regex]::Match($text, 'subnet\s+192\.168\.100\.0\s+netmask\s+255\.255\.255\.0\s*\{')
    if (-not $subnet.Success) {
        Write-Host '[X] 在配置里找不到 192.168.100.0 的 subnet 段，已中止（备份仍在）' -ForegroundColor Red
        exit 1
    }
    $closeIdx = $text.IndexOf('}', $subnet.Index)
    if ($closeIdx -lt 0) {
        Write-Host '[X] subnet 段结构异常，已中止（备份仍在）' -ForegroundColor Red
        exit 1
    }

    $nl    = "`r`n"
    $block = "$nl    host $name {$nl        hardware ethernet $mac;$nl        fixed-address $ip;$nl    }$nl"

    $new = $text.Substring(0, $closeIdx) + $block + $text.Substring($closeIdx)
    [System.IO.File]::WriteAllText($conf, $new, [System.Text.Encoding]::ASCII)
    Write-Host "[OK] 已写入保留条目: $mac -> $ip"
}

# --- 3. 重启 DHCP 服务让配置生效 ---
Write-Host '[..] 重启 VMnetDHCP 服务'
Restart-Service VMnetDHCP -Force
Start-Sleep -Seconds 2

$svc = Get-Service VMnetDHCP
Write-Host "[OK] VMnetDHCP 状态: $($svc.Status)"
if ($svc.Status -ne 'Running') {
    Write-Host '[X] 服务没起来 —— 配置可能有语法错误，用下面这条回滚：' -ForegroundColor Red
    Write-Host "    Copy-Item '$backup' '$conf' -Force; Restart-Service VMnetDHCP -Force" -ForegroundColor Yellow
    exit 1
}

# --- 4. 结果 ---
Write-Host ''
Write-Host '=== 配置里的保留条目 ===' -ForegroundColor Cyan
Get-Content $conf | Select-String -Pattern "host $name" -Context 0,3 | ForEach-Object { $_.Line; $_.Context.PostContext }
Write-Host ''
Write-Host '完成。虚拟机当前已持有 .133，续租时会再次拿到 .133（无需重启虚拟机）。' -ForegroundColor Green
Write-Host '想立刻验证可以在这台虚拟机上跑： sudo dhclient -r ens33 && sudo dhclient ens33' -ForegroundColor Green
