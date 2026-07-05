import pytest

from pica.config import Config
from pica.recognizer import Recognizer


@pytest.mark.asyncio
async def test_recognizer_init():
    cfg = Config()
    r = Recognizer(cfg)
    assert r.cfg == cfg
    assert r.cfg.ai_model == "llava:7b"
