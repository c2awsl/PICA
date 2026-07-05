from pathlib import Path

from PIL import Image, UnidentifiedImageError

from pica.config import Config


def generate_thumbnail(source_path: str | Path, md5_hash: str, cfg: Config) -> Path | None:
    dest = cfg.thumbnails_dir / f"{md5_hash}_{cfg.thumbnail_size[0]}.jpg"
    if dest.exists():
        return dest
    try:
        img = Image.open(source_path)
        img.thumbnail(cfg.thumbnail_size, Image.LANCZOS)
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")
        img.save(dest, "JPEG", quality=cfg.thumbnail_quality)
        return dest
    except (FileNotFoundError, UnidentifiedImageError, OSError):
        return None
