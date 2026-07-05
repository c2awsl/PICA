import threading
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pica.config import Config


class SyncEventHandler(FileSystemEventHandler):
    def __init__(self, cfg: Config, on_new_file):
        self.cfg = cfg
        self.on_new_file = on_new_file

    def _is_image(self, path: str) -> bool:
        ext = Path(path).suffix.lower()
        return ext in self.cfg.allowed_extensions

    def on_created(self, event):
        if not event.is_dir and self._is_image(event.src_path):
            self.on_new_file(event.src_path)

    def on_modified(self, event):
        if not event.is_dir and self._is_image(event.src_path):
            self.on_new_file(event.src_path)


class FileWatcher:
    def __init__(self, cfg: Config, on_new_file):
        self.cfg = cfg
        self.on_new_file = on_new_file
        self._observer = Observer()
        self._handler = SyncEventHandler(cfg, on_new_file)

    def start(self):
        self._observer.schedule(
            self._handler,
            str(self.cfg.sync_dir),
            recursive=True,
        )
        self._observer.start()

    def stop(self):
        self._observer.stop()
        self._observer.join()
