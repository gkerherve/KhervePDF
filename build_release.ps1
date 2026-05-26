# Build script for a KhervePDF release.
#
#   1. Runs PyInstaller against KhervePDF.spec - produces dist\KhervePDF\
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

# 0. Icon - render from icons.app_icon() into a multi-res .ico so
# both the PyInstaller EXE block and the Inno Setup wizard pick up
# the red KP monogram.
Write-Host "==> Generating build\KhervePDF.ico from icons.app_icon()" -ForegroundColor Yellow
py tools\generate_icon.py
if ($LASTEXITCODE -ne 0) { throw "Icon generation failed" }

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
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
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
    # Inno Setup hits Windows' 260-char MAX_PATH when the project
    # lives under a long OneDrive path - sweeping the dist tree
    # plus deeply-nested PySide6 plugins blows the limit. Stage
    # everything ISCC reads into C:\tmp\kpbuild before compiling,
    # then copy the resulting Setup.exe back into installer\.
    $stage = 'C:\tmp\kpbuild'
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Write-Host "==> Staging to $stage (avoids MAX_PATH on long OneDrive paths)" -ForegroundColor Yellow
    Copy-Item 'KhervePDF_setup.iss' "$stage\KhervePDF_setup.iss"
    Copy-Item 'LICENSE'             "$stage\LICENSE"
    New-Item -ItemType Directory -Force -Path "$stage\build" | Out-Null
    Copy-Item 'build\KhervePDF.ico' "$stage\build\KhervePDF.ico"
    Copy-Item 'dist\KhervePDF'      "$stage\dist\KhervePDF" -Recurse
    Push-Location $stage
    try {
        Write-Host "==> $iscc KhervePDF_setup.iss" -ForegroundColor Yellow
        & $iscc KhervePDF_setup.iss
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
    } finally {
        Pop-Location
    }
    $stageInstaller = Join-Path $stage 'installer'
    $localInstaller = Join-Path $ProjectRoot 'installer'
    if (-not (Test-Path $localInstaller)) {
        New-Item -ItemType Directory -Path $localInstaller | Out-Null
    }
    Copy-Item "$stageInstaller\*" $localInstaller -Force
    $setupExe = Join-Path $localInstaller ("Setup_KhervePDF_" + $Version + ".exe")
    if (Test-Path $setupExe) {
        $setupSizeMB = [math]::Round((Get-Item $setupExe).Length / 1MB, 1)
        Write-Host "    Setup.exe: $setupSizeMB MB" -ForegroundColor Green
    }
} else {
    Write-Host ""
    Write-Host "Inno Setup not found - skipping Setup.exe generation." -ForegroundColor Yellow
    Write-Host "Install from https://jrsoftware.org/isinfo.php (free, 3 MB)" -ForegroundColor Yellow
    Write-Host "then re-run this script to produce the installer." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Done. Artifacts:" -ForegroundColor Cyan
Write-Host "  dist\KhervePDF\KhervePDF.exe       (one-folder build)"
Write-Host "  $zipPath"
if ($iscc) {
    Write-Host "  installer\Setup_KhervePDF_$Version.exe   (Windows installer)"
}
