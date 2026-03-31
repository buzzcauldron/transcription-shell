# Local install (Windows): venv, editable install (core deps include tkinterdnd2), Playwright Chromium, protocol submodule.
# Chromium is required for the default lineation backend (glyph_machina). Same role as scripts/install-local.sh — run from PowerShell in the repo root:
#   .\scripts\install-local.ps1
#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

Write-Host "==> Submodules (transcription-protocol)"
if (Test-Path (Join-Path $Root ".git")) {
    try {
        git submodule update --init --recursive vendor/transcription-protocol 2>$null
    } catch { }
}
if (-not (Test-Path "vendor/transcription-protocol/benchmark/validate_schema.py")) {
    Write-Warning "vendor/transcription-protocol missing. Run: git submodule update --init vendor/transcription-protocol"
}

Write-Host "==> Python venv (.venv)"
$venvPy = Join-Path $Root ".venv\Scripts\python.exe"
if ((Test-Path ".venv") -and -not (Test-Path $venvPy)) {
    Write-Host "Removing stale .venv; recreating."
    Remove-Item -Recurse -Force ".venv"
}
if (-not (Test-Path ".venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1

Write-Host "==> pip install (api + dev + optional extras; core package includes tkinterdnd2 for GUI drag-and-drop)"
python -m pip install -U pip
pip install -e ".[api,gemini,xml-xsd,dev]"

Write-Host "==> Playwright Chromium (default lineation: Glyph Machina)"
python -m playwright install chromium

Write-Host "==> GUI sanity (tkinter + tkinterdnd2)"
python -c "import tkinter; import tkinterdnd2" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Warning "tkinter or tkinterdnd2 import failed after pip install. Ensure Python was installed with Tcl/Tk (official python.org installers include it)."
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Write-Host "Tip: copy .env.example to .env and add API keys."
}

Write-Host "==> Done. Activate with: .\.venv\Scripts\Activate.ps1"
Write-Host "    Local setup guide: docs/local-setup.md"
Write-Host "    GUI: transcriber-shell gui"
Write-Host "    CLI: transcriber-shell --help"
