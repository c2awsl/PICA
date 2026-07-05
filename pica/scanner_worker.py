import concurrent.futures
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from sqlalchemy import select

from pica.config import Config
from pica.utils import md5_hash, dhash, get_image_size
from pica.archiver import copy_to_pending
from pica.database import Image, ScanStatus, get_engine, get_session_factory
from pica.grouping import batch_assign_groups

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] scanner: %(message)s",
)
logger = logging.getLogger("scanner")

POLL_INTERVAL = 0.5
CONFIG_RELOAD_INTERVAL = 10.0
BATCH_SIZE = 100
MAX_WALKERS = min(os.cpu_count() or 4, 8)
MAX_WORKERS = min(os.cpu_count() or 4, 8)

# ---------------------------------------------------------------------------
# Worker-process globals (set via initializer)
# ---------------------------------------------------------------------------
_worker_cfg = None


def _worker_init(config_path: str):
    global _worker_cfg
    _worker_cfg = Config.load(Path(config_path))
    _worker_cfg.ensure_dirs()


def _worker_process_file(file_path: str) -> dict | None:
    """Run in a worker subprocess. Returns file metadata dict or None."""
    cfg = _worker_cfg
    path = Path(file_path)

    file_hash = md5_hash(path)
    if not file_hash:
        return None

    dest = copy_to_pending(str(path), file_hash, cfg)
    if not dest:
        return None

    ph = dhash(path)
    width, height = get_image_size(path)

    try:
        size = path.stat().st_size
    except OSError:
        size = 0

    return {
        "filename": path.name,
        "filepath": str(path),
        "md5_hash": file_hash,
        "file_size": size,
        "width": width,
        "height": height,
        "pending_path": str(dest),
        "phash": ph,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _get_status(session, key: str, default=""):
    row = session.get(ScanStatus, key)
    return row.value if row else default


def _set_status(session, key: str, value: str):
    row = session.get(ScanStatus, key)
    if row:
        row.value = str(value)
    else:
        session.add(ScanStatus(key=key, value=str(value)))
    session.commit()


def _inc_status(session, key: str, delta: int = 1):
    val = int(_get_status(session, key, "0")) + delta
    _set_status(session, key, str(val))
    return val


def _poll(session_factory) -> str:
    session = session_factory()
    try:
        return _get_status(session, "command")
    finally:
        session.close()


def _set_command(session_factory, cmd: str):
    session = session_factory()
    try:
        _set_status(session, "command", cmd)
    finally:
        session.close()


def _set_running(session_factory, v: str):
    session = session_factory()
    try:
        _set_status(session, "running", v)
    finally:
        session.close()


def get_scan_sources_from_db(session_factory) -> list[str]:
    session = session_factory()
    try:
        raw = _get_status(session, "scan_sources_json", "[]")
        return json.loads(raw)
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Phase 1: parallel file discovery
# ---------------------------------------------------------------------------
def _walk_path(path: Path, allowed_ext: set) -> list[Path]:
    """Walk a single directory tree, return matching file paths."""
    local = []
    try:
        for entry in path.rglob("*"):
            if entry.is_file() and entry.suffix.lower() in allowed_ext:
                local.append(entry)
    except (PermissionError, OSError) as exc:
        logger.warning("error walking %s: %s", path, exc)
    return local


def discover_files(source_dirs: list[str], allowed_extensions: set) -> list[Path]:
    """Walk multiple source directories in parallel using a thread pool."""
    paths = [Path(d) for d in source_dirs if Path(d).is_dir()]
    if not paths:
        return []

    logger.info("discovering files in %d source dirs (%d threads) …", len(paths), min(len(paths), MAX_WALKERS))

    all_files: list[Path] = []
    lock = threading.Lock()

    def walk_and_collect(dir_path: Path):
        found = _walk_path(dir_path, allowed_extensions)
        with lock:
            all_files.extend(found)
        logger.debug("  %s → %d files", dir_path, len(found))

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(paths), MAX_WALKERS)) as pool:
        list(pool.map(walk_and_collect, paths))

    logger.info("discovery complete: %d files found", len(all_files))
    return all_files


# ---------------------------------------------------------------------------
# Phase 2: parallel file processing
# ---------------------------------------------------------------------------
def _process_batch(
    batch: list[Path],
    session_factory,
    config_path: str,
) -> tuple[int, int, int]:
    """Process a batch of files. Returns (new, skipped, errors)."""
    new = skipped = errors = 0

    # Map file_path strings for pickling
    file_args = [str(p) for p in batch]

    with concurrent.futures.ProcessPoolExecutor(
        max_workers=MAX_WORKERS,
        initializer=_worker_init,
        initargs=(config_path,),
    ) as pool:
        results = list(pool.map(_worker_process_file, file_args))

    # DB operations in main thread — collect all new images, then batch-group
    session = session_factory()
    new_images: list[Image] = []
    try:
        for res in results:
            if res is None:
                errors += 1
                continue

            existing = session.execute(
                select(Image).where(Image.md5_hash == res["md5_hash"])
            ).scalar_one_or_none()
            if existing is not None:
                skipped += 1
                continue

            img = Image(**res)
            session.add(img)
            session.flush()
            new_images.append(img)
            new += 1

        if new_images:
            batch_assign_groups(session, new_images)

        session.commit()
    except Exception:
        session.rollback()
        errors += len(results) - skipped
        logger.exception("batch DB error")
    finally:
        session.close()

    return new, skipped, errors


# ---------------------------------------------------------------------------
# Scan entry point
# ---------------------------------------------------------------------------
def run_scan(cfg: Config, session_factory):
    scan_sources = get_scan_sources_from_db(session_factory) or cfg.scan_sources
    if not scan_sources:
        logger.info("no scan sources configured")
        return

    config_path = str(cfg.config_file) if cfg.config_file else "config.json"

    # --- Phase 1: discover ---
    all_files = discover_files(scan_sources, set(cfg.allowed_extensions))
    total = len(all_files)

    session = session_factory()
    try:
        _set_status(session, "running", "1")
        _set_status(session, "found", str(total))
        _set_status(session, "new", "0")
        _set_status(session, "skipped", "0")
        _set_status(session, "errors", "0")
    finally:
        session.close()

    if total == 0:
        logger.info("no matching files found")
        return

    # --- Phase 2: process in batches ---
    total_new = total_skipped = total_errors = 0
    batch_count = (total + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_idx in range(batch_count):
        # Check control commands before each batch
        cmd = _poll(session_factory)
        if cmd == "stop":
            _set_running(session_factory, "0")
            _set_command(session_factory, "idle")
            logger.info("stop received after batch %d/%d, aborting", batch_idx + 1, batch_count)
            return
        if cmd == "paused":
            _set_running(session_factory, "0")
            _set_command(session_factory, "paused")
            logger.info("pause received, entering paused state")
            while True:
                time.sleep(POLL_INTERVAL)
                cmd2 = _poll(session_factory)
                if cmd2 == "resume":
                    _set_command(session_factory, "")
                    _set_running(session_factory, "1")
                    logger.info("resume received, continuing")
                    break
                if cmd2 in ("stop", "exit"):
                    _set_running(session_factory, "0")
                    _set_command(session_factory, "idle")
                    logger.info("stop/exit during pause, aborting")
                    return

        start = batch_idx * BATCH_SIZE
        end = min(start + BATCH_SIZE, total)
        batch = all_files[start:end]

        logger.info("batch %d/%d (%d files) …", batch_idx + 1, batch_count, len(batch))
        session = session_factory()
        try:
            _set_status(session, "current_file", str(batch[0]))
            _set_status(session, "current_source", str(Path(scan_sources[0]).parent if scan_sources else ""))
        finally:
            session.close()

        n, s, e = _process_batch(batch, session_factory, config_path)
        total_new += n
        total_skipped += s
        total_errors += e

        session = session_factory()
        try:
            _set_status(session, "new", str(total_new))
            _set_status(session, "skipped", str(total_skipped))
            _set_status(session, "errors", str(total_errors))
        finally:
            session.close()

        logger.info("  → +%d new, %d skipped, %d errors (total: %d new)", n, s, e, total_new)

    logger.info("scan complete: %d new, %d skipped, %d errors", total_new, total_skipped, total_errors)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def scan_loop(cfg: Config):
    engine = get_engine(cfg)
    session_factory = get_session_factory(engine)

    def init_status():
        session = session_factory()
        try:
            _set_status(session, "command", "idle")
            _set_status(session, "running", "0")
            _set_status(session, "found", "0")
            _set_status(session, "new", "0")
            _set_status(session, "skipped", "0")
            _set_status(session, "errors", "0")
            _set_status(session, "current_file", "")
            _set_status(session, "current_source", "")
            if cfg.scan_sources:
                _set_status(session, "scan_sources_json", json.dumps(cfg.scan_sources, ensure_ascii=False))
        finally:
            session.close()

    init_status()
    logger.info("scanner worker started (parallel mode: walkers=%d workers=%d batch=%d)", MAX_WALKERS, MAX_WORKERS, BATCH_SIZE)

    last_config_mtime = _config_mtime(cfg)

    while True:
        cmd = _poll(session_factory)

        if cmd == "exit":
            logger.info("exit received, shutting down")
            break

        if cmd == "start":
            logger.info("start received, beginning scan")
            _set_command(session_factory, "")
            run_scan(cfg, session_factory)
            cmd_after = _poll(session_factory)
            if cmd_after != "paused":
                _set_command(session_factory, "idle")
                _set_running(session_factory, "0")
            logger.info("scan finished, returning to poll loop")

        # Periodic config reload
        mtime = _config_mtime(cfg)
        if mtime != last_config_mtime:
            last_config_mtime = mtime
            cfg.reload()
            logger.info("config reloaded")

        time.sleep(POLL_INTERVAL)


def _config_mtime(cfg: Config) -> float:
    try:
        if cfg.config_file and cfg.config_file.exists():
            return cfg.config_file.stat().st_mtime
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    cfg = Config.load(Path(config_path))
    cfg.ensure_dirs()
    scan_loop(cfg)
