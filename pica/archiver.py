import shutil
from pathlib import Path

from pica.config import Config


def copy_to_pending(source_path: str | Path, md5_hash: str, cfg: Config) -> Path | None:
    ext = Path(source_path).suffix
    dest_name = f"{md5_hash}{ext}"
    dest = cfg.pending_dir / dest_name
    if dest.exists():
        return dest
    try:
        shutil.copy2(str(source_path), str(dest))
        return dest
    except (FileNotFoundError, OSError):
        return None


def archive_image(source_path: str | Path, md5_hash: str, category: str, cfg: Config) -> Path | None:
    ext = Path(source_path).suffix
    dest_name = f"{md5_hash}{ext}"
    category_dir = cfg.archive_dir / category
    if not category_dir.exists():
        category_dir.mkdir(parents=True, exist_ok=True)
    dest = category_dir / dest_name
    if dest.exists():
        return dest
    try:
        shutil.copy2(str(source_path), str(dest))
        return dest
    except (FileNotFoundError, OSError):
        return None


def cleanup_pending(pending_path: str | Path):
    p = Path(pending_path)
    if p.exists():
        p.unlink(missing_ok=True)
