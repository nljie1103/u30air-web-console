# Windows PowerShell 5.1 compatible. UTF-8 BOM is added at release.
[CmdletBinding()]
param(
  [string]$AdbPath = "adb",
  [string]$DeviceSerial = "",
  [string]$ConnectAddress = "",
  [string]$BindIp = "",
  [int]$Port = 8765,
  [switch]$NonInteractive,
  [switch]$DiagnoseOnly
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $root
$versionPath = Join-Path $packageRoot "VERSION"
$binaryPath = Join-Path $packageRoot "desktopd"
$remote = "/data/local/tmp/android-web-desktop"

function Run-Adb {
  param([string[]]$ArgList)
  $output = & $script:adbExe @ArgList 2>&1
  $code = $LASTEXITCODE
  if ($code -ne 0) {
    throw ("ADB command failed ({0}): {1}" -f $code, ($output -join " "))
  }
  return ($output -join "`n")
}
function Find-Targets {
  $output = Run-Adb -ArgList @("devices", "-l")
  $targets = @()
  foreach ($line in ($output -split "`r?`n")) {
    $m = [regex]::Match($line, '^\s*(\S+)\s+(device|unauthorized|offline|recovery|sideload|bootloader)(?:\s|$)')
    if ($m.Success) {
      $targets += [pscustomobject]@{ Serial = $m.Groups[1].Value; State = $m.Groups[2].Value }
    }
  }
  return $targets
}
function Describe-Targets {
  param($Targets)
  Write-Host ""
  Write-Host "ADB device list:" -ForegroundColor Cyan
  if (@($Targets).Count -eq 0) {
    Write-Host "  No ADB devices detected." -ForegroundColor Yellow
  }
  foreach ($d in @($Targets)) {
    Write-Host ("  {0,-30} {1}" -f $d.Serial, $d.State)
  }
  if (@($Targets | Where-Object { $_.State -eq "device" }).Count -eq 0) {
    Write-Host "Hints: verify USB debugging and the authorization prompt, or enable ADB over TCP first." -ForegroundColor Yellow
    Write-Host "If you know the device address, run adb connect <private-IP>:5555"
  }
}
function Resolve-Target {
  $devices = @(Find-Targets)
  Describe-Targets $devices
  $ready = @($devices | Where-Object { $_.State -eq "device" })
  if ($DeviceSerial) {
    $selected = @($ready | Where-Object { $_.Serial -eq $DeviceSerial })
    if ($selected.Count -ne 1) { throw "Selected device is not online/authorized: $DeviceSerial" }
    return $selected[0].Serial
  }
  if ($ready.Count -eq 1) { return $ready[0].Serial }
  if ($ready.Count -gt 1) {
    if ($NonInteractive) { throw "Multiple devices detected. Specify -DeviceSerial." }
    for ($i=0;$i -lt $ready.Count;$i++) { Write-Host ("[{0}] {1}" -f ($i+1), $ready[$i].Serial) }
    $answer = Read-Host "Select device number"
    $choice = 0
    if (-not [int]::TryParse($answer,[ref]$choice) -or $choice -lt 1 -or $choice -gt $ready.Count) { throw "Invalid device selection." }
    return $ready[$choice-1].Serial
  }
  if ($NonInteractive) { throw "No authorized ADB device. Check adb devices -l or specify -ConnectAddress." }
  Write-Host ""
  Write-Host "No ready device. Enter a private LAN IP to try ADB over TCP, or press Enter to exit."
  $target = Read-Host "ADB address (example: 192.168.1.20:5555)"
  if (-not $target) { throw "Installation stopped: no authorized ADB device." }
  $target = Normalize-Address $target
  Write-Host (Run-Adb -ArgList @("connect",$target))
  $devices = @(Find-Targets)
  Describe-Targets $devices
  $ready = @($devices | Where-Object { $_.State -eq "device" -and $_.Serial -eq $target })
  if ($ready.Count -ne 1) { throw "ADB connection is not authorized. Check the device authorization prompt." }
  return $target
}
function Normalize-Address {
  param([string]$Value)
  if ($Value -notmatch '^(\d{1,3}(?:\.\d{1,3}){3})(?::(\d{1,5}))?$') { throw "Use a private IPv4 address, optionally with :port." }
  $ip = $Matches[1]
  $tcpPort = 5555
  if ($Matches[2]) { $tcpPort = [int]$Matches[2] }
  if ($tcpPort -lt 1 -or $tcpPort -gt 65535) {throw "Invalid ADB port."}
  $parsed = [System.Net.IPAddress]::Parse($ip).GetAddressBytes()
  if (-not (($parsed[0] -eq 10) -or ($parsed[0] -eq 192 -and $parsed[1] -eq 168) -or ($parsed[0] -eq 172 -and $parsed[1] -ge 16 -and $parsed[1] -le 31))) {
    throw "Use an IPv4 address in the private LAN range."
  }
  return ("{0}:{1}" -f $ip, $tcpPort)
}
function Get-DeviceIps {
  param([string]$Serial)
  $output=Run-Adb -ArgList @("-s",$Serial,"shell","ip","-o","-4","addr","show")
  $ips = @()
  foreach ($line in ($output -split "`r?`n")) {
    $matchesIp = [regex]::Matches($line,'\binet\s+(\d{1,3}(?:\.\d{1,3}){3})/')
    foreach ($x in $matchesIp) {
      $ip = $x.Groups[1].Value
      $pieces = $ip.Split('.')
      $first=[int]$pieces[0];$second=[int]$pieces[1]
      if (($first -eq 10) -or ($first -eq 192 -and $second -eq 168) -or ($first -eq 172 -and $second -ge 16 -and $second -le 31)) {
        if ($ips -notcontains $ip) { $ips += $ip }
      }
    }
  }
  return $ips
}

if ($Port -lt 1024 -or $Port -gt 65535) { throw "The web port must be between 1024 and 65535." }
$cmd = Get-Command $AdbPath -ErrorAction SilentlyContinue
if ($cmd) { $adbExe = $cmd.Source } elseif (Test-Path -LiteralPath $AdbPath) { $adbExe = (Resolve-Path $AdbPath).Path } else {
  throw "ADB not found. Install Android Platform Tools and make adb available in PATH."
}
Write-Host "Android Web Desktop - installer" -ForegroundColor Cyan
if ($ConnectAddress) {
  $normalized = Normalize-Address $ConnectAddress
  Write-Host (Run-Adb -ArgList @("connect",$normalized))
  if (-not $DeviceSerial) { $DeviceSerial = $normalized }
}
$serial = Resolve-Target
Write-Host ("Selected device: {0}" -f $serial) -ForegroundColor Green
if ($DiagnoseOnly) { Write-Host "ADB diagnostics passed."; exit 0 }
if (-not (Test-Path -LiteralPath $versionPath)) { throw "Missing VERSION. Extract the complete release ZIP." }
if (-not (Test-Path -LiteralPath $binaryPath)) { throw "Missing desktopd. Extract the complete release ZIP." }
$ver=(Get-Content -LiteralPath $versionPath -Raw).Trim()
if ($ver -notmatch '^\d+\.\d+\.\d+$') { throw "Invalid package version." }
$abi=(Run-Adb -ArgList @("-s",$serial,"shell","getprop","ro.product.cpu.abi")).Trim()
if ($abi -ne "arm64-v8a") { throw ("Unsupported CPU architecture: {0}; ARM64 required." -f $abi) }
try {
  $ips=@(Get-DeviceIps $serial)
} catch {
  Write-Warning "Unable to query interface IP addresses. You can enter -BindIp manually."
  $ips=@()
}
if ($BindIp) {
  $ip=$BindIp
  if ($ips.Count -gt 0 -and $ips -notcontains $ip) { throw ("Bind IP {0} is not one of the device's detected addresses: {1}" -f $ip,($ips -join ", ")) }
} elseif ($ips.Count -eq 1) {
  $ip=$ips[0]
} elseif ($NonInteractive) {
  throw ("Cannot decide device IP automatically; use -BindIp. Detected: {0}" -f ($ips -join ", "))
} else {
  Write-Host ("Device private IPv4 addresses: {0}" -f ($ips -join ", "))
  $ip=Read-Host "Enter the private IPv4 address used by your browser"
}
if (-not $ip -or $ip -notmatch '^\d{1,3}(?:\.\d{1,3}){3}$') {throw "Invalid device IP."}
Normalize-Address ("{0}:5555" -f $ip) | Out-Null
$address=("{0}:{1}" -f $ip,$Port)
Write-Host ("Installing v{0} for {1}" -f $ver,$address) -ForegroundColor Cyan

# Upload and verify BEFORE interrupting the existing service.
$oldLink = ""
try { $oldLink = (Run-Adb -ArgList @("-s",$serial,"shell","readlink","$remote/current")).Trim() } catch { }
if ($oldLink -eq "releases/$ver/desktopd") {
  throw "This version is already installed. For a safe same-version reinstall, use Windows Manager."
}
$dest="$remote/releases/$ver/desktopd"
Run-Adb -ArgList @("-s",$serial,"shell","mkdir","-p","$remote/releases/$ver") | Out-Null
# Stage new binaries before stopping any existing service.
Run-Adb -ArgList @("-s",$serial,"push",$binaryPath,"$dest.next") | Out-Null
Run-Adb -ArgList @("-s",$serial,"push",(Join-Path $root "start.sh"),"$remote/start.sh.next") | Out-Null
Run-Adb -ArgList @("-s",$serial,"push",(Join-Path $root "stop.sh"),"$remote/stop.sh.next") | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","chmod","700","$dest.next","$remote/start.sh.next","$remote/stop.sh.next") | Out-Null
if ($oldLink -match '^releases/\d+\.\d+\.\d+/desktopd$') {
  Run-Adb -ArgList @("-s",$serial,"shell","sh","$remote/stop.sh") | Out-Null
}
Run-Adb -ArgList @("-s",$serial,"shell","mv","-f","$dest.next",$dest) | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","mv","-f","$remote/start.sh.next","$remote/start.sh") | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","mv","-f","$remote/stop.sh.next","$remote/stop.sh") | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","rm","-f","$remote/current.new") | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","ln","-s","releases/$ver/desktopd","$remote/current.new") | Out-Null
Run-Adb -ArgList @("-s",$serial,"shell","mv","-f","$remote/current.new","$remote/current") | Out-Null
Write-Host (Run-Adb -ArgList @("-s",$serial,"shell","sh","$remote/start.sh",$address))
Write-Host ""
Write-Host ("Web console: http://{0}" -f $address) -ForegroundColor Green
for ($i=0; $i -lt 12; $i++) {
  $output = & $adbExe -s $serial shell cat "$remote/password.txt" 2>$null
  $passwordText = (($output | Select-Object -First 1) -as [string]).Trim()
  if ($LASTEXITCODE -eq 0 -and $passwordText -match '^[0-9a-f]{32}$') {
    Write-Host ("Login password: {0}" -f $passwordText) -ForegroundColor Yellow
    exit 0
  }
  Start-Sleep -Milliseconds 500
}
Write-Warning "Password not available yet. Read the server log via ADB."
exit 1
