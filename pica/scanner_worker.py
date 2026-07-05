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
PROGRESS_INTERVAL = 0.5


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


def scan_loop(cfg: Config):
    engine = get_engine(cfg)
    session_factory = get_session_factory(engine)

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
    finally:
        session.close()

    logger.info("scanner worker started, polling for commands...")

    while True:
        session = session_factory()
        try:
            cmd = get_status(session, "command")
        finally:
            session.close()

        if cmd == "exit":
            logger.info("exit command received, shutting down")
            break

        if cmd == "start":
            logger.info("start command received, beginning scan")
            run_scan(cfg, session_factory)
            session = session_factory()
            try:
                set_status(session, "command", "idle")
                set_status(session, "running", "0")
            finally:
                session.close()
            logger.info("scan finished, returning to poll loop")

        time.sleep(POLL_INTERVAL)


def run_scan(cfg: Config, session_factory):
    if not cfg.scan_sources:
        logger.info("no scan sources configured")
        return

    engine = get_engine(cfg)
    session = session_factory()
    try:
        set_status(session, "running", "1")
        set_status(session, "found", "0")
        set_status(session, "new", "0")
        set_status(session, "skipped", "0")
        set_status(session, "errors", "0")
    finally:
        session.close()

    for src in cfg.scan_sources:
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
            session = session_factory()
            try:
                should_stop = get_status(session, "command") == "stop"
            finally:
                session.close()

            if should_stop:
                logger.info("stop command received, aborting scan")
                session = session_factory()
                try:
                    set_status(session, "running", "0")
                    set_status(session, "command", "idle")
                finally:
                    session.close()
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
            finally:
                session.close()

    logger.info("scan complete")


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
