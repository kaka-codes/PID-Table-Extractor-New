$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$localVenvPython = Join-Path $repoRoot "venv\Scripts\python.exe"
$sharedVenvPython = Join-Path (Split-Path -Parent $repoRoot) "venv\Scripts\python.exe"
$appPath = Join-Path $repoRoot "app.py"

$pythonPath = $null

if (Test-Path $localVenvPython) {
    $pythonPath = $localVenvPython
} elseif (Test-Path $sharedVenvPython) {
    $pythonPath = $sharedVenvPython
}

if (-not (Test-Path $pythonPath)) {
    throw "Expected Python environment was not found. Checked '$localVenvPython' and '$sharedVenvPython'."
}

if (-not (Test-Path $appPath)) {
    throw "Streamlit app was not found at '$appPath'."
}

& $pythonPath -m streamlit run $appPath @args
