import json
import logging
import sys
import time
from pathlib import Path

from sqlalchemy import select

from pica.config import Config
from pica.utils import md5_hash
from pica.thumbnail import generate_thumbnail
from pica.archiver import copy_to_pending
from pica.database import Image, ScanStatus, get_engine, get_session_factory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] scanner: %(message)s",
)
logger = logging.getLogger("scanner")

POLL_INTERVAL = 1.0
CONFIG_RELOAD_INTERVAL = 10.0


def get_status(session, key: str, default=""):
    row = session.get(ScanStatus, key)
    return row.value if row else default


def set_status(session, key: str, value: str):
    row = session.get(ScanStatus, key)
    if row:
        row.value = str(value)
    else:
        session.add(ScanStatus(key=key, value=str(value)))
    session.commit()


def get_scan_sources_from_db(session_factory) -> list[str]:
    session = session_factory()
    try:
        raw = get_status(session, "scan_sources_json", "[]")
        return json.loads(raw)
    finally:
        session.close()


def run_scan(cfg: Config, session_factory):
    scan_sources = get_scan_sources_from_db(session_factory) or cfg.scan_sources
    if not scan_sources:
        logger.info("no scan sources configured")
        return

    session = session_factory()
    try:
        set_status(session, "running", "1")
        set_status(session, "found", "0")
        set_status(session, "new", "0")
        set_status(session, "skipped", "0")
        set_status(session, "errors", "0")
    finally:
        session.close()

    for src in scan_sources:
        src_path = Path(src)
        if not src_path.is_dir():
            logger.warning("scan source not found: %s", src)
            continue

        session = session_factory()
        try:
            set_status(session, "current_source", str(src_path))
        finally:
            session.close()

        logger.info("scanning source: %s", src_path)

        for file_path in src_path.rglob("*"):

            cmd = _poll(session_factory)
            if cmd == "stop":
                _set_running(session_factory, "0")
                _set_command(session_factory, "idle")
                logger.info("stop command received, aborting scan")
                return
            if cmd == "paused":
                _set_running(session_factory, "0")
                _set_command(session_factory, "paused")
                logger.info("pause command received, entering paused state")
                while True:
                    time.sleep(POLL_INTERVAL)
                    cmd2 = _poll(session_factory)
                    if cmd2 == "resume":
                        _set_command(session_factory, "")
                        _set_running(session_factory, "1")
                        logger.info("resume command received, continuing scan")
                        break
                    if cmd2 == "stop":
                        _set_running(session_factory, "0")
                        _set_command(session_factory, "idle")
                        logger.info("stop command received during pause, aborting")
                        return
                    if cmd2 == "exit":
                        _set_running(session_factory, "0")
                        _set_command(session_factory, "idle")
                        logger.info("exit command received during pause, aborting")
                        return

            if file_path.is_dir():
                continue

            ext = file_path.suffix.lower()
            if ext not in cfg.allowed_extensions:
                continue

            session = session_factory()
            try:
                found = int(get_status(session, "found", "0"))
                set_status(session, "found", str(found + 1))
                set_status(session, "current_file", str(file_path))
            finally:
                session.close()

            file_hash = md5_hash(file_path)
            if not file_hash:
                session = session_factory()
                try:
                    err = int(get_status(session, "errors", "0"))
                    set_status(session, "errors", str(err + 1))
                finally:
                    session.close()
                continue

            session = session_factory()
            try:
                existing = session.execute(
                    select(Image).where(Image.md5_hash == file_hash)
                ).scalar_one_or_none()

                if existing is not None:
                    skipped = int(get_status(session, "skipped", "0"))
                    set_status(session, "skipped", str(skipped + 1))
                    continue

                dest = copy_to_pending(str(file_path), file_hash, cfg)
                if dest:
                    width, height = _get_size(file_path)
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
                    new_count = int(get_status(session, "new", "0"))
                    set_status(session, "new", str(new_count + 1))
                else:
                    err = int(get_status(session, "errors", "0"))
                    set_status(session, "errors", str(err + 1))
            except Exception:
                session.rollback()
                err = int(get_status(session, "errors", "0"))
                set_status(session, "errors", str(err + 1))
                logger.exception("error processing: %s", file_path)
            finally:
                session.close()

    logger.info("scan complete")


def _poll(session_factory) -> str:
    session = session_factory()
    try:
        return get_status(session, "command")
    finally:
        session.close()


def _set_command(session_factory, cmd: str):
    session = session_factory()
    try:
        set_status(session, "command", cmd)
    finally:
        session.close()


def _set_running(session_factory, v: str):
    session = session_factory()
    try:
        set_status(session, "running", v)
    finally:
        session.close()


def scan_loop(cfg: Config):
    engine = get_engine(cfg)
    session_factory = get_session_factory(engine)

    def init_status():
        session = session_factory()
        try:
            set_status(session, "command", "idle")
            set_status(session, "running", "0")
            set_status(session, "found", "0")
            set_status(session, "new", "0")
            set_status(session, "skipped", "0")
            set_status(session, "errors", "0")
            set_status(session, "current_file", "")
            set_status(session, "current_source", "")
            if cfg.scan_sources:
                set_status(session, "scan_sources_json", json.dumps(cfg.scan_sources, ensure_ascii=False))
        finally:
            session.close()

    init_status()
    logger.info("scanner worker started, polling for commands...")

    last_config_mtime = _config_mtime(cfg)

    while True:
        cmd = _poll(session_factory)

        if cmd == "exit":
            logger.info("exit command received, shutting down")
            break

        if cmd == "start":
            logger.info("start command received, beginning scan")
            _set_command(session_factory, "")
            run_scan(cfg, session_factory)
            cmd_after = _poll(session_factory)
            if cmd_after != "paused":
                _set_command(session_factory, "idle")
                _set_running(session_factory, "0")
            logger.info("scan finished, returning to poll loop")

        # Periodically reload config to pick up changes
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


def _get_size(filepath: str | Path):
    try:
        from PIL import Image as PILImage
        with PILImage.open(filepath) as img:
            return img.size
    except Exception:
        return None, None


if __name__ == "__main__":
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    cfg = Config.load(Path(config_path))
    cfg.ensure_dirs()
    scan_loop(cfg)
