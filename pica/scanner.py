import logging
import threading
import time
from pathlib import Path

from sqlalchemy import select

from pica.config import Config
from pica.database import Image, get_session_factory, get_engine
from pica.archiver import copy_to_pending
from pica.utils import md5_hash

logger = logging.getLogger(__name__)


class ScanProgress:
    def __init__(self):
        self.running = False
        self.found = 0
        self.new = 0
        self.skipped = 0
        self.errors = 0
        self.current_file = ""
        self.current_source = ""
        self._lock = threading.Lock()

    def reset(self):
        with self._lock:
            self.found = 0
            self.new = 0
            self.skipped = 0
            self.errors = 0
            self.current_file = ""
            self.current_source = ""

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "found": self.found,
                "new": self.new,
                "skipped": self.skipped,
                "errors": self.errors,
                "current_file": self.current_file,
                "current_source": self.current_source,
            }

    def set_running(self, v: bool):
        with self._lock:
            self.running = v


scan_progress = ScanProgress()


def scan_sources(cfg: Config):
    if not cfg.scan_sources:
        logger.info("no scan sources configured")
        return

    scan_progress.reset()
    scan_progress.set_running(True)

    engine = get_engine(cfg)
    session_factory = get_session_factory(engine)

    for src in cfg.scan_sources:
        src_path = Path(src)
        if not src_path.is_dir():
            logger.warning("scan source not found: %s", src)
            continue

        scan_progress.current_source = str(src_path)
        logger.info("scanning source: %s", src_path)

        for file_path in src_path.rglob("*"):
            if not scan_progress.running:
                return
            if file_path.is_dir():
                continue

            ext = file_path.suffix.lower()
            if ext not in cfg.allowed_extensions:
                continue

            scan_progress.current_file = str(file_path)
            with scan_progress._lock:
                scan_progress.found += 1

            file_hash = md5_hash(file_path)
            if not file_hash:
                with scan_progress._lock:
                    scan_progress.errors += 1
                continue

            session = session_factory()
            try:
                existing = session.execute(
                    select(Image).where(Image.md5_hash == file_hash)
                ).scalar_one_or_none()
                if existing is not None:
                    with scan_progress._lock:
                        scan_progress.skipped += 1
                    continue

                dest = copy_to_pending(str(file_path), file_hash, cfg)
                if dest:
                    width, height = _get_size(file_path)
                    from pica.thumbnail import generate_thumbnail
                    generate_thumbnail(dest, file_hash, cfg)
                    img = Image(
                        filename=file_path.name,
                        filepath=str(file_path),
                        md5_hash=file_hash,
                        file_size=file_path.stat().st_size,
                        width=width,
                        height=height,
                        pending_path=str(dest),
                    )
                    session.add(img)
                    session.commit()
                    with scan_progress._lock:
                        scan_progress.new += 1
                else:
                    with scan_progress._lock:
                        scan_progress.errors += 1
            except Exception:
                session.rollback()
                with scan_progress._lock:
                    scan_progress.errors += 1
            finally:
                session.close()

    scan_progress.set_running(False)
    snap = scan_progress.snapshot()
    logger.info("scan complete: found=%d new=%d skipped=%d errors=%d",
                snap["found"], snap["new"], snap["skipped"], snap["errors"])


def _get_size(filepath: str | Path):
    try:
        from PIL import Image as PILImage
        with PILImage.open(filepath) as img:
            return img.size
    except Exception:
        return None, None


def run_scan_in_thread(cfg: Config):
    t = threading.Thread(target=scan_sources, args=(cfg,), daemon=True)
    t.start()
    return t
