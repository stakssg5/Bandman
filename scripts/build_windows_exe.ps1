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
$entryCli = Join-Path $repoRoot "apps/scan_until_profit.py"

if (-not (Test-Path $entry)) {
    throw "Entry script not found: $entry"
}
if (-not (Test-Path $entryCli)) {
    throw "Entry script not found: $entryCli"
}

$buildArgs = @("-m", "PyInstaller", "--onefile", "--name", "CryptoPRPlus")

if ($Noconsole) { $buildArgs += "--noconsole" }

$buildArgs += $entry

Write-Host "Building Windows executable..." -ForegroundColor Cyan
& $PythonExe $buildArgs

Write-Host "Building CLI scanner executable..." -ForegroundColor Cyan
& $PythonExe -m PyInstaller --onefile --name ScanUntilProfit --paths $repoRoot $entryCli

Write-Host "Done. EXEs should be in the 'dist' folder." -ForegroundColor Green
