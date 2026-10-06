param(
    [ValidateSet('gui', 'preview', 'check')]
    [string]$Mode = 'gui'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'

try {
    if (-not (Test-Path -LiteralPath $pythonExe)) {
        if ($Mode -eq 'check') { throw 'Missing .venv. Run start.cmd to set up Python dependencies.' }
        Write-Host 'Creating a Python 3.12 virtual environment...'
        if (Get-Command py -ErrorAction SilentlyContinue) {
            & py -3.12 -m venv .venv
        } elseif (Get-Command python -ErrorAction SilentlyContinue) {
            & python -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
            if ($LASTEXITCODE -ne 0) { throw 'Please install Python 3.12 with the Python launcher.' }
            & python -m venv .venv
        } else {
            throw 'Please install Python 3.12 from https://www.python.org/downloads/windows/'
        }
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the virtual environment. Python 3.12 is required.' }
    }
    & $pythonExe -c 'import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'The existing .venv must use Python 3.12. It has not been modified.' }

    & $pythonExe scripts/check_dependencies.py
    if ($LASTEXITCODE -ne 0) {
        if ($Mode -eq 'check') { throw 'Dependency check failed. Run start.cmd to install dependencies.' }
        Write-Host 'Installing project dependencies into .venv...'
        & $pythonExe -m pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your network and retry.' }
        & $pythonExe scripts/check_dependencies.py
        if ($LASTEXITCODE -ne 0) { throw 'Dependency verification failed.' }
    }
    if ($Mode -eq 'check') {
        Write-Host 'Environment ready. No game actions were performed.'
    } elseif ($Mode -eq 'preview') {
        & $pythonExe scripts/diagnostics/scan_test.py --auto-start --auto-close --cross-sample --preview
        if ($LASTEXITCODE -ne 0) { throw 'Preview exited with an error.' }
    } else {
        & $pythonExe main.py
        if ($LASTEXITCODE -ne 0) { throw 'Application exited with an error.' }
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
exit 0
