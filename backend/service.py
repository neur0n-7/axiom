import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from indexer import (
    read_file, upsert_file, delete_file, get_mtime,
    init_db, scan_files, get_config, get_default_root, ALLOWED_EXTENSIONS
)


def get_root():
    return get_config("root_dir", get_default_root())


# -------------------------
# INITIAL BUILD
# -------------------------

def initial_index():
    root = get_root()
    print(f"🔄 Initial indexing of: {root}")
    files = scan_files(root)
    for path in files:
        content = read_file(path)
        upsert_file(path, content, get_mtime(path))
    print(f"✅ Indexed {len(files)} files")


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
# START SERVICE
# -------------------------

def start_watcher_background():
    """Kick off the initial index + filesystem watcher without blocking the
    caller. Used by the FastAPI process (main.py) so a single sidecar does
    both indexing and serving search requests."""

    def _run():
        initial_index()
        root = get_root()
        observer = Observer()
        observer.schedule(Handler(), root, recursive=True)
        observer.start()
        print(f"🚀 File watcher running on: {root}")

    threading.Thread(target=_run, daemon=True).start()


def start_service():
    """Blocking standalone entrypoint, kept for running `python service.py`
    directly outside of the Tauri sidecar."""
    init_db()
    initial_index()

    root = get_root()
    print(f"🚀 File watcher running on: {root}")

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
