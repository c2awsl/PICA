import hashlib
from pathlib import Path


def md5_hash(filepath: str | Path) -> str | None:
    h = hashlib.md5()
    try:
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, OSError):
        return None


def get_image_size(filepath: str | Path) -> tuple[int, int] | tuple[None, None]:
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            return img.size
    except Exception:
        return None, None
