import tempfile
from pathlib import Path

import pytest

from pica.config import Config
from pica.archiver import copy_to_pending, archive_image, cleanup_pending


@pytest.fixture
def cfg(tmp_path):
    c = Config(project_root=tmp_path)
    c.__post_init__()
    c.ensure_dirs()
    return c


def test_copy_to_pending(cfg):
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        f.write(b"fake_image_data")
        src = f.name
    try:
        dest = copy_to_pending(src, "testhash", cfg)
        assert dest is not None
        assert dest.exists()
        assert dest.name == "testhash.jpg"
    finally:
        Path(src).unlink(missing_ok=True)
        cleanup_pending(dest)


def test_archive_image(cfg):
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        f.write(b"fake_png_data")
        src = f.name
    try:
        dest = archive_image(src, "archhash", "人物", cfg)
        assert dest is not None
        assert dest.exists()
        assert "人物" in str(dest)
        assert dest.name == "archhash.png"
    finally:
        Path(src).unlink(missing_ok=True)
        dest.unlink(missing_ok=True)


def test_cleanup_pending(cfg):
    p = cfg.pending_dir / "delete_me.txt"
    p.write_text("test")
    assert p.exists()
    cleanup_pending(p)
    assert not p.exists()
