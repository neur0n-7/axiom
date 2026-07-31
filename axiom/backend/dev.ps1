# Runs the backend directly against the venv with hot-reload, for use
# alongside `pnpm tauri dev` (which skips spawning the sidecar in debug
# builds). Faster inner loop than rebuilding the PyInstaller sidecar.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

& ".\venv\Scripts\python.exe" -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
