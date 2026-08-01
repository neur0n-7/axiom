<img src="docs/banner.png" width="100%" alt="Axiom: Local Semantic Search App" />

A local desktop search app for your files. Axiom indexes a folder you choose
and lets you search it by keyword, by meaning (semantic), or a blend of both. Axiom does not send any data to leave your machine.

<br clear="right" />

## Features

- **Three search modes** - keyword, semantic, and hybrid (combination of both)
- **Live indexing** - background file watcher looks for new, edited, and deleted files automatically
- **Fully local** - the search index (SQLite) and the embedding model run on your machine without anything uploaded to other sites, which is insecure
- **Configurable scope** - pick any folder to index, with exclusion patterns for subfolders you don't want scanned (defaults skip things like `node_modules`, `.git`, `venv`, build output, and other dotfile/config directories)
- **Reveal in Explorer** - click a search result to open it selected in your system file browser

## Stack

- **Frontend**: React + TypeScript, bundled with Vite
- **Desktop shell**: [Tauri](https://tauri.app/) (Rust)
- **Backend**: Python (FastAPI) packaged into executable with
  PyInstaller and run as a Tauri sidecar process
- **Search**: SQLite for storage, [sentence-transformers](https://www.sbert.net/)
  (`all-MiniLM-L6-v2`) for semantic embeddings

## Project structure

```
axiom/
├── src/                    React frontend
├── src-tauri/              Tauri/Rust desktop shell
│   ├── src/lib.rs          App entry point, sidecar process management
│   └── binaries/           Built backend sidecar executable (generated)
└── backend/                Python search backend
    ├── main.py             FastAPI app / HTTP endpoints
    ├── indexer.py          File scanning, chunking, embeddings, DB access
    ├── service.py          File watcher + background indexing
    ├── dev.ps1             Run the backend directly for local development (instead of having to build it)
    └── build_sidecar.ps1   Freeze the backend into a sidecar executable
```

## Setup

**Prerequisites:**

- [Node.js](https://nodejs.org/) and [pnpm](https://pnpm.io/)
- [Rust](https://www.rust-lang.org/tools/install) (for Tauri)
- Python 3.11+

**1. Install frontend dependencies**

```powershell
pnpm install
```

**2. Set up the backend**

```powershell
cd backend
python -m venv venv
./venv/Scripts/pip install -r requirements.txt
cd ..
```

**3. Run it**

In debug builds, Axiom doesn't spawn the bundled backend sidecar because rebuilding the backend executable on every change is super slow. Instead, run the backend directly, then start the Tauri app:

```powershell
./backend/dev.ps1

# in another terminal/cmd
pnpm tauri dev
```

## Building

```powershell
# Freeze the Python backend into a sidecar executable
./backend/build_sidecar.ps1

# Build the Tauri app (bundles the sidecar automatically)
pnpm tauri build
```

The first run of `build_sidecar.ps1` downloads the embedding model so it can be bundled into the executable for offline use afterward.

## Platform support

Axiom has been built and tested on Windows. The backend and frontend are cross-platform, but a macOS/Linux build requires freezing the sidecar on that OS (PyInstaller doesn't cross-compile), which I will do in future releases but is not implemented right now.

## License

Axiom is licensed under the [Apache License 2.0](https://www.apache.org/licenses/LICENSE-2.0).
