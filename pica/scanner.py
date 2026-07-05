import logging
from pathlib import Path

from pica.config import Config
from pica.database import Image, get_engine, get_session_factory
from pica.archiver import copy_to_pending
from pica.utils import md5_hash
from pica.thumbnail import generate_thumbnail

logger = logging.getLogger(__name__)


def scan_sources(cfg: Config):
    """
    Core scan logic: walks source directories, dedup by MD5, copies to pending,
    generates thumbnails.  Used by scanner_worker.py (separate process).
    """
    if not cfg.scan_sources:
        logger.info("no scan sources configured")
        return

    engine = get_engine(cfg)
    session_factory = get_session_factory(engine)

    for src in cfg.scan_sources:
        src_path = Path(src)
        if not src_path.is_dir():
            logger.warning("scan source not found: %s", src)
            continue

        logger.info("scanning source: %s", src_path)

        for file_path in src_path.rglob("*"):
            if file_path.is_dir():
                continue

            ext = file_path.suffix.lower()
            if ext not in cfg.allowed_extensions:
                continue

            file_hash = md5_hash(file_path)
            if not file_hash:
                logger.warning("unable to hash: %s", file_path)
                continue

            session = session_factory()
            try:
                from sqlalchemy import select
                existing = session.execute(
                    select(Image).where(Image.md5_hash == file_hash)
                ).scalar_one_or_none()
                if existing is not None:
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
                else:
                    logger.warning("copy_to_pending failed: %s", file_path)
            except Exception:
                session.rollback()
                logger.exception("error processing: %s", file_path)
            finally:
                session.close()


def _get_size(filepath: str | Path):
    try:
        from PIL import Image as PILImage
        with PILImage.open(filepath) as img:
            return img.size
    except Exception:
        return None, None
