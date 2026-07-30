from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional
from indexer import (
    init_db, simple_search, semantic_search, hybrid_search,
    get_config, set_config, get_default_root, DEFAULT_EXCLUDES
)

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
    print("⚡ Initializing DB...")
    init_db()
    print("✅ Ready")


@app.get("/")
def root():
    return {"status": "Axiom backend running"}


# -------------------------
# SEARCH
# -------------------------

@app.get("/search")
def search_endpoint(
    q: str = Query(...),
    mode: str = Query(default="hybrid"),  # "keyword" | "semantic" | "hybrid"
    limit: int = Query(default=10)
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


# -------------------------
# CONFIG
# -------------------------

class ConfigPayload(BaseModel):
    root_dir: Optional[str] = None
    exclude_patterns: Optional[List[str]] = None


@app.get("/config")
def get_config_endpoint():
    return {
        "root_dir": get_config("root_dir", get_default_root()),
        "exclude_patterns": get_config("exclude_patterns", DEFAULT_EXCLUDES),
    }


@app.post("/config")
def set_config_endpoint(payload: ConfigPayload):
    if payload.root_dir is not None:
        set_config("root_dir", payload.root_dir)
    if payload.exclude_patterns is not None:
        set_config("exclude_patterns", payload.exclude_patterns)
    return {"status": "saved"}
