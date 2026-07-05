# PICA Tauri Production Builder
# Builds a standalone desktop installer for Windows/macOS/Linux
#
# Prerequisites:
#   - Rust, Tauri CLI v2, Python 3.11+
#   - Windows: WiX Toolset for .msi (https://wixtoolset.org/)
#   - macOS: Xcode
#   - Linux: various system libraries (see Tauri docs)

Write-Host "=== PICA Tauri Production Build ===" -ForegroundColor Cyan

$hasCargo = Get-Command cargo -ErrorAction SilentlyContinue
if (-not $hasCargo) {
    Write-Host "ERROR: cargo not found. Install Rust from https://rustup.rs" -ForegroundColor Red
    exit 1
}

Write-Host "Building PICA desktop installer..." -ForegroundColor Green
Write-Host "This will create an installer in src-tauri/target/release/bundle/" -ForegroundColor Gray

cd (Split-Path $PSScriptRoot -Parent)
cargo tauri build

Write-Host "Build complete!" -ForegroundColor Green
