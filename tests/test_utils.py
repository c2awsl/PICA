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
