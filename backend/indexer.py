import os
import sys
import sqlite3
import json
import numpy as np

ALLOWED_EXTENSIONS = {".txt", ".py", ".md", ".json", ".js", ".ts"}


def get_app_dir():
    """Directory the backend's data lives next to.

    When frozen by PyInstaller (running as a Tauri sidecar), the process's
    CWD isn't reliable, so data must be anchored to the executable's own
    location instead.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_bundle_dir():
    """Directory bundled read-only resources (like the embedding model)
    live in. In a PyInstaller onefile build this is the temp extraction
    dir (_MEIPASS), which is NOT the same as the exe's own directory, so
    this is kept separate from get_app_dir()."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


DATA_DIR = os.path.join(get_app_dir(), "data")
DB_PATH = os.path.join(DATA_DIR, "index.db")

MODEL_NAME = "all-MiniLM-L6-v2"

# Lazy-loaded model
_model = None

def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        # Prefer the bundled copy (see build_sidecar.ps1) so search works
        # offline; fall back to the HF Hub name for local dev, where it's
        # cached normally after the first download.
        bundled = os.path.join(get_bundle_dir(), "model_cache", MODEL_NAME)
        _model = SentenceTransformer(bundled if os.path.isdir(bundled) else MODEL_NAME)
    return _model


# -------------------------
# DB SETUP
# -------------------------

def get_conn():
    os.makedirs(DATA_DIR, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS files (
            path TEXT PRIMARY KEY,
            content TEXT,
            modified REAL,
            embedding BLOB
        )
    """)

    # Migrate existing DBs that lack the embedding column
    existing = {row[1] for row in c.execute("PRAGMA table_info(files)")}
    if "embedding" not in existing:
        c.execute("ALTER TABLE files ADD COLUMN embedding BLOB")

    # Chunk-level embeddings: long files are split into overlapping word
    # chunks so semantic search isn't blind past the first ~500 words.
    c.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            path TEXT,
            chunk_index INTEGER,
            content TEXT,
            embedding BLOB,
            PRIMARY KEY (path, chunk_index)
        )
    """)

    # Config table for persisted settings
    c.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    conn.commit()
    conn.close()


# -------------------------
# CONFIG
# -------------------------

def get_config(key: str, default=None):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT value FROM config WHERE key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return default


def set_config(key: str, value):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO config (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
    """, (key, json.dumps(value)))
    conn.commit()
    conn.close()


def get_default_root():
    """Returns ~/Downloads as a sensible default."""
    return str(os.path.join(os.path.expanduser("~"), "Downloads"))


DEFAULT_EXCLUDES = [
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".cache", "coverage",
    "$RECYCLE.BIN", "System Volume Information", "AppData",
    "Windows", "Program Files", "Program Files (x86)"
]


# -------------------------
# FILE SYSTEM
# -------------------------

def scan_files(root_dir: str, exclude_patterns: list[str] = None):
    if exclude_patterns is None:
        exclude_patterns = get_config("exclude_patterns", DEFAULT_EXCLUDES)

    files = []

    excludes_lower = {p.lower() for p in exclude_patterns}

    for root, dirs, filenames in os.walk(root_dir):
        # Prune excluded dirs in-place (exact name match, not substring --
        # otherwise e.g. "distillation-notes" gets excluded by "dist")
        dirs[:] = [d for d in dirs if d.lower() not in excludes_lower]

        for f in filenames:
            if any(f.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                files.append(os.path.join(root, f))

    return files


def read_file(path: str):
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except:
        return ""


def get_mtime(path: str):
    try:
        return os.path.getmtime(path)
    except:
        return 0


# -------------------------
# EMBEDDING HELPERS
# -------------------------

CHUNK_WORDS = 500
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_words: int = CHUNK_WORDS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split into overlapping word windows so long files are fully searchable."""
    words = text.split()
    if not words:
        return []

    step = chunk_words - overlap
    pieces = []
    for start in range(0, len(words), step):
        piece = words[start:start + chunk_words]
        if not piece:
            break
        pieces.append(" ".join(piece))
        if start + chunk_words >= len(words):
            break
    return pieces


def embed_text(text: str) -> bytes:
    """Embed a single short string (used for search queries)."""
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return vec.astype(np.float32).tobytes()


def embed_texts(texts: list[str]) -> np.ndarray:
    """Batch-embed multiple chunks at once (much faster than one at a time)."""
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True)
    return vecs.astype(np.float32)

# db operations #######################################################3

def upsert_file(path, content, modified, compute_embedding=True):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO files (path, content, modified)
        VALUES (?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            content=excluded.content,
            modified=excluded.modified
    """, (path, content, modified))

    c.execute("DELETE FROM chunks WHERE path=?", (path,))

    if compute_embedding and content.strip():
        try:
            pieces = chunk_text(content)
            if pieces:
                vecs = embed_texts(pieces)
                c.executemany(
                    "INSERT INTO chunks (path, chunk_index, content, embedding) VALUES (?, ?, ?, ?)",
                    [(path, i, piece, vec.tobytes()) for i, (piece, vec) in enumerate(zip(pieces, vecs))]
                )
        except Exception as e:
            print(f"Embedding failed for {path}: {e}")

    conn.commit()
    conn.close()


def clear_index():
    """Wipe all indexed files/chunks. Used when the search root changes so
    stale entries from the old directory don't linger in results."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM files")
    c.execute("DELETE FROM chunks")
    conn.commit()
    conn.close()


def delete_file(path):
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM files WHERE path=?", (path,))
    c.execute("DELETE FROM chunks WHERE path=?", (path,))
    conn.commit()
    conn.close()


def get_stored_mtimes():
    """Map of path -> stored modified time, so reindexing can skip files
    that haven't changed since they were last embedded."""
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT path, modified FROM files")
    rows = c.fetchall()
    conn.close()
    return dict(rows)


def load_index():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT path, content FROM files")
    rows = c.fetchall()
    conn.close()
    return [{"path": r[0], "content": r[1]} for r in rows]


def simple_search(query: str, limit: int = 10):
    query = query.lower()
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT path, content FROM files WHERE content LIKE ? ESCAPE '\\'
    """, (f"%{escaped}%",))
    rows = c.fetchall()
    conn.close()

    scored = []
    for path, content in rows:
        score = 0
        path_l = path.lower()
        content_l = content.lower()

        if query in path_l:
            score += 120
        filename = os.path.basename(path_l)
        if query == filename:
            score += 200

        occurrences = content_l.count(query)
        if occurrences > 0:
            score += min(occurrences * 15, 60)
            idx = content_l.find(query)
            position_score = max(0, 80 - (idx // 50))
            score += position_score
            snippet = content[max(0, idx - 60): idx + 160]
        else:
            snippet = ""

        size_penalty = min(len(content_l) // 20000, 30)
        score -= size_penalty

        if any(ext in path_l for ext in [".py", ".js", ".ts"]):
            score += 10

        scored.append({"path": path, "snippet": snippet, "score": score})

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


EMBED_DIM = 384  # all-MiniLM-L6-v2 output size


def semantic_search(query: str, limit: int = 10):
    query_vec = np.frombuffer(embed_text(query), dtype=np.float32)

    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT path, chunk_index, embedding FROM chunks")
    rows = c.fetchall()

    if not rows:
        conn.close()
        return []

    matrix = np.frombuffer(b"".join(r[2] for r in rows), dtype=np.float32).reshape(len(rows), EMBED_DIM)
    sims = matrix @ query_vec  # already normalized -> cosine similarity

    # Keep only the best-scoring chunk per file
    best_by_path = {}
    for i, (path, chunk_index, _) in enumerate(rows):
        score = float(sims[i])
        if path not in best_by_path or score > best_by_path[path][0]:
            best_by_path[path] = (score, chunk_index)

    ranked = sorted(best_by_path.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]
    if not ranked:
        conn.close()
        return []

    placeholders = ",".join("(?,?)" for _ in ranked)
    params = [v for path, (_, chunk_index) in ranked for v in (path, chunk_index)]
    c.execute(
        f"SELECT path, chunk_index, content FROM chunks WHERE (path, chunk_index) IN ({placeholders})",
        params
    )
    content_by_key = {(r[0], r[1]): r[2] for r in c.fetchall()}
    conn.close()

    results = []
    for path, (score, chunk_index) in ranked:
        content = content_by_key.get((path, chunk_index), "")
        snippet = " ".join(content.split()[:40])
        results.append({"path": path, "snippet": snippet, "score": score})
    return results


def _min_max_normalize(scores: list[float]) -> tuple[float, float]:
    """Returns (min, range) so callers can do (score - min) / range, robust to negative scores."""
    if not scores:
        return 0.0, 1.0
    lo, hi = min(scores), max(scores)
    return lo, (hi - lo) or 1.0


def hybrid_search(query: str, limit: int = 10, semantic_weight: float = 0.5):
    """Merge keyword + semantic scores (min-max normalized)."""
    keyword_results = simple_search(query, limit=50)
    semantic_results = semantic_search(query, limit=50)

    kw_map = {r["path"]: r for r in keyword_results}
    kw_min, kw_range = _min_max_normalize([r["score"] for r in keyword_results])

    sem_map = {r["path"]: r for r in semantic_results}
    sem_min, sem_range = _min_max_normalize([r["score"] for r in semantic_results])

    all_paths = set(kw_map) | set(sem_map)
    merged = []

    for path in all_paths:
        kw_score = (kw_map[path]["score"] - kw_min) / kw_range if path in kw_map else 0
        sem_score = (sem_map[path]["score"] - sem_min) / sem_range if path in sem_map else 0
        combined = (1 - semantic_weight) * kw_score + semantic_weight * sem_score

        if path in kw_map and kw_map[path]["snippet"]:
            snippet = kw_map[path]["snippet"]
        elif path in sem_map:
            snippet = sem_map[path]["snippet"]
        else:
            snippet = ""

        merged.append({"path": path, "snippet": snippet, "score": combined})

    merged.sort(key=lambda x: x["score"], reverse=True)
    return merged[:limit]
