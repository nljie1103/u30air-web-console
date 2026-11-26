$ErrorActionPreference = "Stop"
$scriptPath = (Resolve-Path "$PSScriptRoot/../../web-console/deploy/install_windows.ps1").Path
$bytes = [System.IO.File]::ReadAllBytes($scriptPath)
if ($bytes.Length -lt 4 -or $bytes[0] -ne 239 -or $bytes[1] -ne 187 -or $bytes[2] -ne 191) {
  throw "PowerShell 5.1 install script must use UTF-8 BOM."
}
$tokens = $null
$errors = $null
[System.Management.Automation.Language.Parser]::ParseFile($scriptPath,[ref]$tokens,[ref]$errors) | Out-Null
if ($errors.Count -gt 0) { throw ("PowerShell parse errors: " + ($errors | Out-String)) }

$mock = Join-Path $env:RUNNER_TEMP "mock-adb.cmd"
@'
@echo off
if "%~1"=="connect" (
 echo connected to %~2
 exit /b 0
)
if "%~1"=="-s" goto serialcmd
if not "%~1"=="devices" exit /b 0
echo List of devices attached
if "%AWD_TEST_SCENARIO%"=="one" echo usb-001     device product:demo
if "%AWD_TEST_SCENARIO%"=="unauthorized" echo usb-001     unauthorized
if "%AWD_TEST_SCENARIO%"=="offline" echo usb-001     offline
if "%AWD_TEST_SCENARIO%"=="multiple" (
 echo usb-001     device
 echo usb-002     device
)
if "%AWD_TEST_SCENARIO%"=="connected" echo 192.168.1.20:5555     device
exit /b 0
:serialcmd
if "%~3"=="push" (echo upload success & exit /b 0)
if "%~3"=="shell" (
  if "%~4"=="getprop" (echo arm64-v8a & exit /b 0)
  if "%~4"=="ip" (echo 2: wlan0 inet 192.168.1.20/24 brd 192.168.1.255 scope global wlan0 & exit /b 0)
  if "%~4"=="readlink" (
    if "%AWD_TEST_CURRENT%"=="same" echo releases/2.0.0/desktopd
    exit /b 0
  )
  if "%~4"=="cat" (echo 0123456789abcdef0123456789abcdef & exit /b 0)
  if "%~4"=="sh" (echo Launch requested & exit /b 0)
)
exit /b 0
'@ | Set-Content -LiteralPath $mock -Encoding ASCII

function Check {
  param([string]$Scenario,[bool]$ShouldSucceed,[string]$Match,[string[]]$Extra=@())
  $env:AWD_TEST_SCENARIO = $Scenario
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $output = (& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $scriptPath -AdbPath $mock -NonInteractive -DiagnoseOnly @Extra 2>&1 | Out-String)
  $ErrorActionPreference = $previousPreference
  $ok=($LASTEXITCODE -eq 0)
  if ($ok -ne $ShouldSucceed) { throw ("Scenario '$Scenario' expected success=$ShouldSucceed; actual=$ok; output=$output") }
  if ($Match -and $output -notmatch [regex]::Escape($Match)) {throw ("Scenario '$Scenario' missing text '$Match': $output")}
  Write-Host ("PASS: {0} / {1}" -f $Scenario,$ShouldSucceed)
}
Check "one" $true "usb-001"
Check "unauthorized" $false "unauthorized"
Check "offline" $false "offline"
Check "empty" $false "No ADB devices detected"
Check "multiple" $false "Multiple devices"
Check "multiple" $true "usb-002" @("-DeviceSerial","usb-002")
Check "connected" $true "192.168.1.20:5555" @("-ConnectAddress","192.168.1.20:5555")
Write-Host "Windows PowerShell 5.1 parser and ADB diagnostics passed."

# Exercise the entire installer path with a simulated authorized device.
$root = Resolve-Path "$PSScriptRoot/../../web-console"
$versionFile = Join-Path $root "VERSION"
$binaryFile = Join-Path $root "desktopd"
try {
  Set-Content -LiteralPath $versionFile -Value "2.0.0" -Encoding ASCII
  [System.IO.File]::WriteAllBytes($binaryFile,[byte[]](1,2,3,4))
  $env:AWD_TEST_SCENARIO="one"
  $previousPreference = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  $output=(& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $scriptPath -AdbPath $mock -NonInteractive 2>&1 | Out-String)
  $ErrorActionPreference = $previousPreference
  if ($LASTEXITCODE -ne 0 -or $output -notmatch 'Login password:') {
    throw ("Full simulated installation failed: " + $output)
  }
  Write-Host "PASS: end-to-end installation (mock ADB)"
  $env:AWD_TEST_CURRENT="same"
  $ErrorActionPreference = "Continue"
  $blocked = (& powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File $scriptPath -AdbPath $mock -NonInteractive 2>&1 | Out-String)
  $ErrorActionPreference = $previousPreference
  if ($LASTEXITCODE -eq 0 -or $blocked -notmatch "already installed") {
    throw ("Same-version install should be safely refused: " + $blocked)
  }
  Write-Host "PASS: same-version reinstall guard (mock ADB)"
} finally {
  $env:AWD_TEST_CURRENT=""
  Remove-Item -LiteralPath $versionFile,$binaryFile -ErrorAction SilentlyContinue
}
# Expected failure in the final negative test must not become this script's exit code.
# Exceptions above still terminate this test with a nonzero status.
exit 0
