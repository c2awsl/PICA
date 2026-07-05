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


def dhash(filepath: str | Path, hash_size: int = 8) -> str | None:
    """Difference hash (perceptual hash). Returns hex string, None on failure."""
    try:
        from PIL import Image
        with Image.open(filepath) as img:
            img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
            diff = []
            for row in range(hash_size):
                for col in range(hash_size):
                    diff.append(img.getpixel((col, row)) < img.getpixel((col + 1, row)))
            bits = 0
            hex_chars = []
            for i, bit in enumerate(diff):
                if bit:
                    bits |= 1 << (i % 8)
                if (i + 1) % 8 == 0:
                    hex_chars.append(f"{bits:02x}")
                    bits = 0
            return "".join(hex_chars)
    except Exception:
        return None


def hamming_distance(hash1: str, hash2: str) -> int:
    """Hamming distance between two hex-encoded perceptual hashes."""
    if len(hash1) != len(hash2):
        return 64
    b1 = int(hash1, 16)
    b2 = int(hash2, 16)
    return (b1 ^ b2).bit_count()
