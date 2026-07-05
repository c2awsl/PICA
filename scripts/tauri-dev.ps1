# PICA Tauri Development Launcher
# Requires: Rust, Tauri CLI v2, Python 3.11+
#
# Install Tauri CLI: cargo install tauri-cli --version "^2.0"
# Or via npm: npm install -g @tauri-apps/cli

Write-Host "=== PICA Tauri Dev Launcher ===" -ForegroundColor Cyan
Write-Host "Make sure dependencies are installed:" -ForegroundColor Yellow
Write-Host "  - Rust: https://rustup.rs" -ForegroundColor Gray
Write-Host "  - Tauri CLI: cargo install tauri-cli --version '^2.0'" -ForegroundColor Gray
Write-Host "  - Python 3.11+ with dependencies: pip install -r requirements.txt" -ForegroundColor Gray
Write-Host ""

# Check prerequisites
$hasCargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $hasCargo) {
    Write-Host "ERROR: cargo not found. Install Rust from https://rustup.rs" -ForegroundColor Red
    exit 1
}

$hasPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $hasPython) {
    Write-Host "ERROR: python not found. Install Python 3.11+" -ForegroundColor Red
    exit 1
}

Write-Host "Starting PICA desktop app..." -ForegroundColor Green

# Launch Tauri in dev mode (Rust code will start the Python server)
cd (Split-Path $PSScriptRoot -Parent)
cargo tauri dev
