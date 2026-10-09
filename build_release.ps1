$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Missing .venv. Run .\run.ps1 first."
}

& $Python -m pip install --upgrade pyinstaller
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }

$oldProcesses = Get-CimInstance Win32_Process -Filter "Name='pythonw.exe'" |
    Where-Object { $_.ExecutablePath -like "*$ProjectRoot\.venv\Scripts\pythonw.exe" -and $_.CommandLine -like "*camp_vision.app*" }
foreach ($process in $oldProcesses) {
    Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue
}

if (Test-Path (Join-Path $ProjectRoot "build")) { Remove-Item -LiteralPath (Join-Path $ProjectRoot "build") -Recurse -Force }
if (Test-Path (Join-Path $ProjectRoot "dist")) { Remove-Item -LiteralPath (Join-Path $ProjectRoot "dist") -Recurse -Force }

& (Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe") `
    --noconfirm `
    --clean `
    --onedir `
    --windowed `
    --name CampVision `
    --icon (Join-Path $ProjectRoot "assets\camp-vision.ico") `
    --paths (Join-Path $ProjectRoot "src") `
    --add-data "data;data" `
    --add-data "assets\card_templates;assets\card_templates" `
    --collect-all rapidocr_onnxruntime `
    --collect-all onnxruntime `
    --collect-all pyopencl `
    (Join-Path $ProjectRoot "launcher.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

$Release = Join-Path $ProjectRoot "dist\CampVision"
$Guide = Get-ChildItem -LiteralPath $ProjectRoot -Filter "*.txt" -File |
    Sort-Object Length -Descending |
    Select-Object -First 1
if (-not $Guide) { throw "Usage guide not found." }
Copy-Item -LiteralPath $Guide.FullName -Destination (Join-Path $Release $Guide.Name) -Force
Copy-Item -LiteralPath (Join-Path $ProjectRoot "data\roster.json") -Destination (Join-Path $Release "roster-backup.json") -Force

$Zip = Join-Path $ProjectRoot "dist\CampVision-portable.zip"
if (Test-Path $Zip) { Remove-Item -LiteralPath $Zip -Force }
Compress-Archive -Path $Release -DestinationPath $Zip -CompressionLevel Optimal

Write-Host "Release directory: $Release"
Write-Host "Share archive: $Zip"
