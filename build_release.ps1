# Build script for a KhervePDF release.
#
#   1. Runs PyInstaller against KhervePDF.spec — produces dist\KhervePDF\
#   2. Zips that folder into dist\KhervePDF_<version>.zip
#   3. Runs Inno Setup (ISCC.exe) against KhervePDF_setup.iss to make
#      installer\Setup_KhervePDF_<version>.exe
#
# Step 3 requires Inno Setup 6:
#   https://jrsoftware.org/isinfo.php  (free, ~3 MB installer)
# If ISCC.exe isn't on PATH or under the default Program Files path,
# the script prints how to install it and exits cleanly after step 2.
#
# Run from an admin PowerShell so the install step's tests work too:
#   powershell -ExecutionPolicy Bypass -File .\build_release.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = $PSScriptRoot
Set-Location $ProjectRoot

# Read the version from khervepdf/__init__.py so the artifact names
# match without us having to keep two copies in sync.
$initPy = Get-Content (Join-Path $ProjectRoot 'khervepdf\__init__.py') -Raw
if ($initPy -match '__version__\s*=\s*"([^"]+)"') {
    $Version = $Matches[1]
} else {
    $Version = "0.0"
}
Write-Host "Building KhervePDF v$Version" -ForegroundColor Cyan

# 1. PyInstaller
Write-Host "==> pyinstaller KhervePDF.spec --noconfirm" -ForegroundColor Yellow
py -m PyInstaller KhervePDF.spec --noconfirm
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# 2. Zip
$zipPath = Join-Path $ProjectRoot ("dist\KhervePDF_" + $Version + ".zip")
if (Test-Path $zipPath) { Remove-Item $zipPath }
Write-Host "==> Compressing dist\KhervePDF -> $zipPath" -ForegroundColor Yellow
Compress-Archive -Path 'dist\KhervePDF\*' -DestinationPath $zipPath -CompressionLevel Optimal
$zipSizeMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 1)
Write-Host "    $zipSizeMB MB" -ForegroundColor Green

# 3. Inno Setup
$iscc = $null
$candidates = @(
    'C:\Program Files (x86)\Inno Setup 6\ISCC.exe',
    'C:\Program Files\Inno Setup 6\ISCC.exe',
    'C:\Program Files (x86)\Inno Setup 5\ISCC.exe'
)
foreach ($c in $candidates) {
    if (Test-Path $c) { $iscc = $c; break }
}
if (-not $iscc) {
    $onPath = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($onPath) { $iscc = $onPath.Source }
}

if ($iscc) {
    Write-Host "==> $iscc KhervePDF_setup.iss" -ForegroundColor Yellow
    & $iscc KhervePDF_setup.iss
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    $setupExe = Join-Path $ProjectRoot ("installer\Setup_KhervePDF_" + $Version + ".exe")
    if (Test-Path $setupExe) {
        $setupSizeMB = [math]::Round((Get-Item $setupExe).Length / 1MB, 1)
        Write-Host "    Setup.exe: $setupSizeMB MB" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "Inno Setup not found — skipping Setup.exe generation." -ForegroundColor Yellow
    Write-Host "Install from https://jrsoftware.org/isinfo.php (free, ~3 MB)" -ForegroundColor Yellow
    Write-Host "then re-run this script to produce the installer." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Artifacts:" -ForegroundColor Cyan
Write-Host "  dist\KhervePDF\KhervePDF.exe       (one-folder build)"
Write-Host "  $zipPath"
if ($iscc) {
    Write-Host "  installer\Setup_KhervePDF_$Version.exe   (Windows installer)"
}
