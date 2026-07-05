# PICA startup script for Windows
param(
    [string]$ConfigPath = ""
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

# Check if virtual environment exists, create if not
if (-not (Test-Path -LiteralPath "$ProjectRoot\.venv")) {
    Write-Host "Creating Python virtual environment..." -ForegroundColor Cyan
    python -m venv .venv
    & "$ProjectRoot\.venv\Scripts\pip" install -r requirements.txt
}

# Activate venv and run
Write-Host "Starting PICA..." -ForegroundColor Green
if ($ConfigPath) {
    & "$ProjectRoot\.venv\Scripts\python" -m pica --config $ConfigPath
} else {
    & "$ProjectRoot\.venv\Scripts\python" -m pica
}
