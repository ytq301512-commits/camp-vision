$ErrorActionPreference = "Stop"
$dist = Join-Path (Get-Location) "dist\CampVision-fixed"
$work = Join-Path (Get-Location) "build\CampVision-fixed"
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
& (Join-Path (Get-Location) ".venv\Scripts\pyinstaller.exe") --noconfirm --clean --onedir --windowed --name CampVision --icon (Join-Path (Get-Location) "assets\camp-vision.ico") --paths (Join-Path (Get-Location) "src") --add-data "data;data" --collect-all rapidocr_onnxruntime --collect-all onnxruntime --distpath $dist --workpath $work (Join-Path (Get-Location) "launcher.py")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
$release = Join-Path $dist "CampVision"
$guide = Get-ChildItem -LiteralPath (Get-Location) -Filter "*.txt" -File | Sort-Object Length -Descending | Select-Object -First 1
Copy-Item $guide.FullName (Join-Path $release $guide.Name) -Force
Copy-Item (Join-Path (Get-Location) "data\roster.json") (Join-Path $release "roster-backup.json") -Force
$zip = Join-Path (Get-Location) "dist\CampVision-fixed-portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $release -DestinationPath $zip -CompressionLevel Optimal
Get-Item (Join-Path $release "CampVision.exe"), (Join-Path $release $guide.Name), $zip | Select-Object FullName,Length
