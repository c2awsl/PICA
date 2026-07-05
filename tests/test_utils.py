import tempfile
from pathlib import Path

import pytest

from pica.utils import md5_hash


def test_md5_hash():
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"hello world")
        tmp = f.name
    try:
        h = md5_hash(tmp)
        assert h == "5eb63bbbe01eeed093cb22bb8f5acdc3"
    finally:
        Path(tmp).unlink(missing_ok=True)


def test_md5_hash_nonexistent():
    h = md5_hash("nonexistent_file_xyz.jpg")
    assert h is None


def test_dhash():
    from pica.utils import dhash, hamming_distance
    import tempfile, os
    from PIL import Image
    tmpdir = tempfile.mkdtemp()
    a = os.path.join(tmpdir, "a.png")
    b = os.path.join(tmpdir, "b.png")
    Image.new("RGB", (64, 64), color="red").save(a)
    Image.new("RGB", (64, 64), color="blue").save(b)
    ha = dhash(a)
    hb = dhash(b)
    assert ha and hb
    assert len(ha) == 16
    assert len(hb) == 16
    dist = hamming_distance(ha, hb)
    assert 0 <= dist <= 64
    assert hamming_distance(ha, ha) == 0


def test_dhash_invalid():
    from pica.utils import dhash
    assert dhash("nonexistent.png") is None
