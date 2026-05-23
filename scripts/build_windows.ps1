param(
    [string]$AppName = "IATREINER"
)

$ErrorActionPreference = "Stop"

Set-Location (Resolve-Path "$PSScriptRoot\..")

Write-Host "Installing build tools..."
python -m pip install --upgrade pip
python -m pip install pyinstaller

if (Test-Path "client\requirements.txt") {
    python -m pip install -r client\requirements.txt
}

Write-Host "Cleaning old build output..."
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
Remove-Item -Force "$AppName.spec" -ErrorAction SilentlyContinue

Write-Host "Building portable executable..."
pyinstaller `
    --onefile `
    --windowed `
    --clean `
    --name $AppName `
    --version-file packaging\windows_version_info.txt `
    client\volunteer_app.py

if (-not (Test-Path "dist\$AppName.exe")) {
    throw "PyInstaller did not produce dist\$AppName.exe"
}

Write-Host "Portable executable created: dist\$AppName.exe"

$isccCommand = Get-Command iscc -ErrorAction SilentlyContinue
$isccPath = if ($isccCommand) { $isccCommand.Source } else { $null }
if (-not $isccPath) {
    $defaultIscc = Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"
    if (Test-Path $defaultIscc) {
        $isccPath = $defaultIscc
    }
}

if ($isccPath) {
    Write-Host "Building installer with Inno Setup..."
    & $isccPath "installer\IATREINER.iss"
    Write-Host "Installer created under installer\Output"
} else {
    Write-Host "Inno Setup compiler not found. Skipping installer build."
}
