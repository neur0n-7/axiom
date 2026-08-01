import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from indexer import (
    read_file, upsert_file, delete_file, get_mtime, clear_index,
    get_stored_mtimes, init_db, scan_files, get_config, get_default_root,
    ALLOWED_EXTENSIONS
)

_observer = None
_observer_lock = threading.Lock()

_progress_lock = threading.Lock()
_progress = {"indexing": False, "total": 0, "done": 0}


def get_progress():
    with _progress_lock:
        return dict(_progress)


def _set_progress(**kwargs):
    with _progress_lock:
        _progress.update(kwargs)


def get_root():
    return get_config("root_dir", get_default_root())


# -------------------------
# INITIAL BUILD
# -------------------------

def initial_index():
    root = get_root()
    print(f"🔄 Initial indexing of: {root}")
    files = scan_files(root)
    stored = get_stored_mtimes()

    to_index = [(p, get_mtime(p)) for p in files]
    to_index = [(p, m) for p, m in to_index if stored.get(p) != m]

    _set_progress(indexing=True, total=len(to_index), done=0)

    for path, mtime in to_index:
        content = read_file(path)
        upsert_file(path, content, mtime)
        with _progress_lock:
            _progress["done"] += 1

    _set_progress(indexing=False)
    print(f"✅ Indexed {len(to_index)} changed files ({len(files) - len(to_index)} unchanged, skipped)")


# -------------------------
# WATCHER
# -------------------------

class Handler(FileSystemEventHandler):

    def on_created(self, event):
        if not event.is_directory:
            self.update(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self.update(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            delete_file(event.src_path)
            print(f"DELETED: {event.src_path}")

    def update(self, path):
        ext = os.path.splitext(path)[1]
        if ext not in ALLOWED_EXTENSIONS:
            return
        try:
            content = read_file(path)
            upsert_file(path, content, get_mtime(path))
            print(f"UPDATED: {path}")
        except:
            pass


# -------------------------
# OBSERVER MANAGEMENT
# -------------------------

def _start_observer(root):
    global _observer
    observer = Observer()
    observer.schedule(Handler(), root, recursive=True)
    observer.start()
    with _observer_lock:
        _observer = observer


def _stop_observer():
    global _observer
    with _observer_lock:
        if _observer is not None:
            _observer.stop()
            _observer.join()
            _observer = None


# -------------------------
# START SERVICE
# -------------------------

def start_watcher_background():
    """Kick off the initial index + filesystem watcher without blocking the
    caller. Used by the FastAPI process (main.py) so a single sidecar does
    both indexing and serving search requests."""

    def _run():
        initial_index()
        root = get_root()
        _start_observer(root)
        print(f"🚀 File watcher running on: {root}")

    threading.Thread(target=_run, daemon=True).start()


def reindex_all():
    """Wipe the index and rebuild it from the (possibly new) root_dir, then
    point the watcher at that directory. Called when root_dir changes so
    results from the old directory don't keep showing up."""
    _stop_observer()
    clear_index()
    initial_index()
    root = get_root()
    _start_observer(root)
    print(f"File watcher running on: {root}")


def start_service():
    """Blocking standalone entrypoint, kept for running `python service.py`
    directly outside of the Tauri sidecar."""
    init_db()
    initial_index()

    root = get_root()
    print(f"File watcher running on: {root}")

    observer = Observer()
    observer.schedule(Handler(), root, recursive=True)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()

    observer.join()


if __name__ == "__main__":
    start_service()
