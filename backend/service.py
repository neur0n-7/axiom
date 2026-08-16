import time
import os
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from indexer import (
    read_file, upsert_file, upsert_files_batch, INDEX_BATCH_SIZE,
    delete_file, delete_path_prefix, get_mtime, clear_index,
    get_stored_mtimes, init_db, scan_files, get_config,
    ALLOWED_EXTENSIONS, DATA_DIR
)

active_observer = None
observer_lock = threading.Lock()

# prevent infinite loop from happening by excluding axiom's db
DATA_DIR_ABS = os.path.abspath(DATA_DIR) + os.sep


def is_app_data_path(path):
    return os.path.abspath(path).startswith(DATA_DIR_ABS)


def is_hidden_path(path):
    # mirrors scan_files()'s dotfile skip so watcher events stay consistent with a full reindex
    return any(part.startswith(".") for part in os.path.normpath(path).split(os.sep)[:-1])


def is_ignored(path):
    return is_app_data_path(path) or is_hidden_path(path)


progress_lock = threading.Lock()
progress = {"indexing": False, "total": 0, "done": 0}


def get_progress():
    with progress_lock:
        return dict(progress)


def set_progress(**kwargs):
    with progress_lock:
        progress.update(kwargs)


def get_root():
    return get_config("root_dir")


# init build #########################################################################

def initial_index():
    root = get_root()
    if root is None:
        return
    print(f"🔄 Initial indexing of: {root}")
    files = scan_files(root)
    stored = get_stored_mtimes()

    to_index = [(p, get_mtime(p)) for p in files]
    to_index = [(p, m) for p, m in to_index if stored.get(p) != m]

    stale = set(stored) - set(files)
    for path in stale:
        delete_file(path)

    set_progress(indexing=True, total=len(to_index), done=0)

    def mark_done(path):
        with progress_lock:
            progress["done"] += 1

    for i in range(0, len(to_index), INDEX_BATCH_SIZE):
        batch = to_index[i:i + INDEX_BATCH_SIZE]
        items = [(path, read_file(path), mtime) for path, mtime in batch]
        upsert_files_batch(items, on_file_done=mark_done)

    set_progress(indexing=False)
    print(f"✅ Indexed {len(to_index)} changed files ({len(files) - len(to_index)} unchanged, skipped)")


# watcher #########################################################################


class Handler(FileSystemEventHandler):

    def on_created(self, event):
        if not event.is_directory and not is_ignored(event.src_path):
            self.update(event.src_path)

    def on_modified(self, event):
        if not event.is_directory and not is_ignored(event.src_path):
            self.update(event.src_path)

    def on_deleted(self, event):
        if is_ignored(event.src_path):
            return
        if event.is_directory:
            delete_path_prefix(event.src_path)
            print(f"DELETED DIR: {event.src_path}")
        else:
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

##########################################################################

def start_observer(root):
    global active_observer
    new_observer = Observer()
    new_observer.schedule(Handler(), root, recursive=True)
    new_observer.start()
    with observer_lock:
        active_observer = new_observer


def stop_observer():
    global active_observer
    with observer_lock:
        if active_observer is not None:
            active_observer.stop()
            active_observer.join()
            active_observer = None


##########################################################################


def start_watcher_background():
    # start off the initial index + filesystem watcher without blocking the caller

    def run():
        initial_index()
        root = get_root()
        start_observer(root)
        print(f"File watcher running on: {root}")

    threading.Thread(target=run, daemon=True).start()


def reindex_all():
    # wipes and rebuilds the index for a new root_dir, then re-points the watcher
    stop_observer()
    clear_index()
    initial_index()
    root = get_root()
    start_observer(root)
    print(f"File watcher running on: {root}")


def start_service():
    # blocking entrypoint for running `python service.py` directly, outside the sidecar
    init_db()

    root = get_root()
    if root is None:
        print("No search directory configured yet - waiting for first-run setup")
        return

    initial_index()
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
