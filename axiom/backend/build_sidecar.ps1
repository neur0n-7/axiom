# Builds axiom-backend (main.py + the folded-in file watcher) into a single
# executable and drops it into src-tauri/binaries with the target-triple
# suffix Tauri's sidecar mechanism expects.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$targetTriple = (rustc -vV | Select-String '^host: (.+)$').Matches[0].Groups[1].Value
Write-Host "Target triple: $targetTriple"

$python = Join-Path $root "venv\Scripts\python.exe"
& $python -m pip install --quiet --upgrade pyinstaller

& $python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name axiom-backend `
    --distpath dist `
    --workpath build `
    --hidden-import uvicorn.logging `
    --hidden-import uvicorn.loops `
    --hidden-import uvicorn.loops.auto `
    --hidden-import uvicorn.protocols `
    --hidden-import uvicorn.protocols.http `
    --hidden-import uvicorn.protocols.http.auto `
    --hidden-import uvicorn.protocols.websockets `
    --hidden-import uvicorn.protocols.websockets.auto `
    --hidden-import uvicorn.lifespan `
    --hidden-import uvicorn.lifespan.on `
    --collect-all sentence_transformers `
    --collect-all transformers `
    --collect-all torch `
    --collect-all tokenizers `
    --collect-all safetensors `
    --collect-all huggingface_hub `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

$destDir = Join-Path $root "..\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null

$destFile = Join-Path $destDir "axiom-backend-$targetTriple.exe"
Copy-Item (Join-Path $root "dist\axiom-backend.exe") $destFile -Force

Write-Host "Sidecar built: $destFile"
