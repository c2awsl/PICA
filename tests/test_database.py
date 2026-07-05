import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pica.database import Base, Image, ImageStatus


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_create_image(db_session):
    img = Image(
        filename="test.jpg",
        filepath="sync_dir/test.jpg",
        md5_hash="abc123",
        file_size=1024,
        width=1920,
        height=1080,
        status=ImageStatus.PENDING,
        suggested_category=json.dumps(["风景", "自然"], ensure_ascii=False),
        suggested_tags=json.dumps(["日落", "海滩"], ensure_ascii=False),
        ai_model="llava:7b",
        ai_latency_ms=1500.0,
    )
    db_session.add(img)
    db_session.commit()

    saved = db_session.get(Image, img.id)
    assert saved is not None
    assert saved.filename == "test.jpg"
    assert saved.md5_hash == "abc123"
    assert saved.status == ImageStatus.PENDING
    assert saved.suggested_category_list == ["风景", "自然"]
    assert saved.suggested_tags_list == ["日落", "海滩"]


def test_confirm_image(db_session):
    img = Image(
        filename="test.jpg",
        filepath="sync_dir/test.jpg",
        md5_hash="def456",
        status=ImageStatus.PENDING,
    )
    db_session.add(img)
    db_session.commit()

    img.status = ImageStatus.CONFIRMED
    img.confirmed_category = json.dumps(["人物"], ensure_ascii=False)
    img.confirmed_tags = json.dumps(["肖像", "微笑"], ensure_ascii=False)
    img.confirmed_at = datetime.utcnow()
    db_session.commit()

    saved = db_session.get(Image, img.id)
    assert saved.status == ImageStatus.CONFIRMED
    assert saved.confirmed_category_list == ["人物"]
    assert saved.confirmed_tags_list == ["肖像", "微笑"]


def test_to_dict(db_session):
    img = Image(
        filename="test.jpg",
        filepath="sync_dir/test.jpg",
        md5_hash="ghi789",
        status=ImageStatus.PENDING,
        suggested_category=json.dumps(["食物"], ensure_ascii=False),
    )
    db_session.add(img)
    db_session.commit()

    d = img.to_dict()
    assert d["filename"] == "test.jpg"
    assert d["status"] == "pending"
    assert d["suggested_category"] == ["食物"]


def test_md5_unique_constraint(db_session):
    img1 = Image(
        filename="a.jpg",
        filepath="sync_dir/a.jpg",
        md5_hash="same",
    )
    db_session.add(img1)
    db_session.commit()

    img2 = Image(
        filename="b.jpg",
        filepath="sync_dir/b.jpg",
        md5_hash="same",
    )
    db_session.add(img2)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()
