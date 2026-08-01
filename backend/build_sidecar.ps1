# Freezes main.py into a sidecar exe and drops it into src-tauri/binaries
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$targetTriple = (rustc -vV | Select-String '^host: (.+)$').Matches[0].Groups[1].Value
Write-Host "Target triple: $targetTriple"

$python = Join-Path $root "venv\Scripts\python.exe"
& $python -m pip install --quiet --upgrade pyinstaller

$modelDir = Join-Path $root "model_cache\all-MiniLM-L6-v2"
if (-not (Test-Path $modelDir)) {
    Write-Host "Downloading embedding model for offline bundling..."
    & $python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2').save('model_cache/all-MiniLM-L6-v2')"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to download embedding model"
    }
}

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
    --add-data "model_cache\all-MiniLM-L6-v2;model_cache\all-MiniLM-L6-v2" `
    main.py

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller build failed"
}

$destDir = Join-Path $root "..\src-tauri\binaries"
New-Item -ItemType Directory -Force -Path $destDir | Out-Null

$destFile = Join-Path $destDir "axiom-backend-$targetTriple.exe"
Copy-Item (Join-Path $root "dist\axiom-backend.exe") $destFile -Force

Write-Host "Sidecar built: $destFile"
