param(
    [string]$PythonExe = "python",
    [switch]$Noconsole
)

$ErrorActionPreference = "Stop"

Write-Host "Installing PyInstaller..." -ForegroundColor Cyan
& $PythonExe -m pip install --upgrade pip pyinstaller

$root = Split-Path -Parent $MyInvocation.MyCommand.Definition
$repoRoot = Resolve-Path (Join-Path $root "..")
$entry = Join-Path $repoRoot "apps/wallet_checker_gui.py"

if (-not (Test-Path $entry)) {
    throw "Entry script not found: $entry"
}

$buildArgs = @("-m", "PyInstaller", "--onefile", "--name", "WalletChecker")

if ($Noconsole) { $buildArgs += "--noconsole" }

$buildArgs += $entry

Write-Host "Building Windows executable..." -ForegroundColor Cyan
& $PythonExe $buildArgs

Write-Host "Done. EXE should be in the 'dist' folder." -ForegroundColor Green
