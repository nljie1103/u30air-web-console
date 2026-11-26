# Windows 10/11 portable smoke test with Mark-of-the-Web on packaged CLR DLLs.
# A successful bare --self-test is insufficient: it never imports pywebview WinForms.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$zip = Join-Path $repo "dist\AndroidWebDesktopManager-Portable.zip"
if (!(Test-Path -LiteralPath $zip)) { throw "Portable ZIP missing: $zip" }
$work = Join-Path $env:RUNNER_TEMP "AWD-portable-motw-test"
if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $work -Force
$portable = Join-Path $work "AndroidWebDesktopManager"
$exe = Join-Path $portable "AndroidWebDesktopManager.exe"
$config = "$exe.config"
$runtime = Join-Path $portable "_internal\pythonnet\runtime\Python.Runtime.dll"
$clrloader = Join-Path $portable "_internal\clr_loader\ffi\dlls\amd64\ClrLoader.dll"
$webviewCore = Join-Path $portable "_internal\webview\lib\Microsoft.Web.WebView2.Core.dll"
$webviewForms = Join-Path $portable "_internal\webview\lib\Microsoft.Web.WebView2.WinForms.dll"
foreach ($path in @($exe, $config, $runtime, $clrloader, $webviewCore, $webviewForms)) {
  if (!(Test-Path -LiteralPath $path)) { throw "Portable runtime file missing: $path" }
}
[xml]$xml = Get-Content -LiteralPath $config -Raw
if ($xml.configuration.runtime.loadFromRemoteSources.enabled -ne "true") {
  throw "Application-local CLR configuration is missing"
}
Write-Host "Verified packaged executable's .NET loadFromRemoteSources configuration"

# Simulate Windows Explorer's downloaded ZIP Zone.Identifier propagated to DLLs.
# This modifies only files inside RUNNER_TEMP.
foreach ($dll in @($runtime, $clrloader, $webviewCore, $webviewForms)) {
  Set-Content -LiteralPath $dll -Stream Zone.Identifier -Value @("[ZoneTransfer]", "ZoneId=3") -Encoding ascii
  $streams = @(Get-Item -LiteralPath $dll -Stream Zone.Identifier -ErrorAction Stop)
  if ($streams.Count -lt 1) { throw "Failed to simulate Internet zone on $dll" }
  Write-Host "Marked as Internet-zone: $($dll.Substring($portable.Length + 1))"
}

# Import pythonnet, initialize CLR and launch WebView2, not merely --self-test.
$process = Start-Process -FilePath $exe -ArgumentList "--gui-smoke-test" -PassThru
try {
  $null = $process.WaitForExit(40000)
  $process.Refresh()
  if (!$process.HasExited) { throw "Internet-marked portable GUI timed out" }
  if ($process.ExitCode -ne 0) { throw "Internet-marked portable GUI failed: $($process.ExitCode)" }
  Write-Host "PASS: Portable EXE initialized WebView2 with Internet-marked runtime files"
}
finally {
  if (!$process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
}
