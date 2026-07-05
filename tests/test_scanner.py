from pathlib import Path

import pytest

from pica.config import Config


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
