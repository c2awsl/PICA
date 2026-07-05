from pathlib import Path

import pytest

from pica.config import Config
from pica.scanner import ScanProgress


def test_scan_progress():
    sp = ScanProgress()
    assert sp.snapshot()["running"] is False
    assert sp.snapshot()["found"] == 0

    sp.set_running(True)
    assert sp.snapshot()["running"] is True

    with sp._lock:
        sp.found = 10
        sp.new = 5
        sp.skipped = 3
        sp.errors = 2
    snap = sp.snapshot()
    assert snap["found"] == 10
    assert snap["new"] == 5
    assert snap["skipped"] == 3
    assert snap["errors"] == 2

    sp.reset()
    snap = sp.snapshot()
    assert snap["found"] == 0
    assert snap["new"] == 0


def test_scan_sources_empty(cfg):
    from pica.scanner import scan_sources
    scan_sources(cfg)
    # should not crash with empty scan_sources


@pytest.fixture
def cfg(tmp_path):
    c = Config(project_root=tmp_path)
    c.__post_init__()
    c.ensure_dirs()
    return c
