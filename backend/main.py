import multiprocessing
import sys

multiprocessing.freeze_support()

# force UTF-8
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from indexer import (
    init_db, simple_search, semantic_search, hybrid_search,
    get_config, set_config, get_default_root, DEFAULT_EXCLUDES
)
import threading
from service import start_watcher_background, reindex_all, get_progress

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    print("Initializing DB...")
    init_db()
    if get_config("root_dir") is not None:
        start_watcher_background()
    else:
        print("No search directory configured yet - waiting for first-run setup")
    print("Ready")


@app.get("/")
def root():
    return {"status": "Axiom backend running"}


@app.get("/status")
def status_endpoint():
    return get_progress()


# search #########################################################################


@app.get("/search")
def search_endpoint(
    q: str = Query(...),
    mode: str = Query(default="hybrid"),
    limit: int = Query(default=10, ge=1, le=100)
):
    if not q.strip():
        return {"results": []}

    if mode == "keyword":
        results = simple_search(q, limit=limit)
    elif mode == "semantic":
        results = semantic_search(q, limit=limit)
    else:
        results = hybrid_search(q, limit=limit)

    return {
        "query": q,
        "mode": mode,
        "count": len(results),
        "results": results
    }


# config #########################################################################

class ConfigPayload(BaseModel):
    root_dir: Optional[str] = None
    exclude_patterns: Optional[List[str]] = None


@app.get("/config")
def get_config_endpoint():
    return {
        "root_dir": get_config("root_dir", get_default_root()),
        "exclude_patterns": get_config("exclude_patterns", DEFAULT_EXCLUDES),
        "is_first_run": get_config("root_dir") is None,
    }


@app.post("/config")
def set_config_endpoint(payload: ConfigPayload):
    # very first save always counts as a change
    root_changed = (
        payload.root_dir is not None
        and payload.root_dir != get_config("root_dir")
    )

    if payload.root_dir is not None:
        set_config("root_dir", payload.root_dir)
    if payload.exclude_patterns is not None:
        set_config("exclude_patterns", payload.exclude_patterns)

    if root_changed:
        # remove stale entries from the old directory
        threading.Thread(target=reindex_all, daemon=True).start()

    return {"status": "saved"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
