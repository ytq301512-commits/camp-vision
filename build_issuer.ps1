$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$dist = Join-Path $root "dist\CampVisionLicenseIssuer"
$work = Join-Path $root "build\CampVisionLicenseIssuer"
if (-not (Test-Path (Join-Path $root "license_private_key.json"))) {
    throw "Missing license_private_key.json. Keep the issuer private key beside this script."
}
if (Test-Path $dist) { Remove-Item $dist -Recurse -Force }
if (Test-Path $work) { Remove-Item $work -Recurse -Force }
& (Join-Path $root ".venv\Scripts\pyinstaller.exe") `
    --noconfirm --clean --onedir --windowed `
    --name CampVisionLicenseIssuer `
    --icon (Join-Path $root "assets\camp-vision.ico") `
    --paths (Join-Path $root "tools") `
    --add-data "license_private_key.json;." `
    --distpath $dist --workpath $work `
    (Join-Path $root "tools\license_issuer_gui.py")
if ($LASTEXITCODE -ne 0) { throw "Issuer build failed." }
Write-Host "Issuer: $(Join-Path $dist 'CampVisionLicenseIssuer\CampVisionLicenseIssuer.exe')"
