$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    Write-Host "First launch: preparing the Python environment..."
    $BundledPython = "C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
    if (Test-Path $BundledPython) {
        & $BundledPython -m venv (Join-Path $ProjectRoot ".venv")
    } else {
        py -3.12 -m venv (Join-Path $ProjectRoot ".venv")
    }
    & $Python -m pip install --upgrade pip
}

Set-Location $ProjectRoot
& $Python -c "import camp_vision" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the application package..."
    & $Python -m pip install --editable $ProjectRoot
}
& $Python -m camp_vision.app
