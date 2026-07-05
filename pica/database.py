import enum
import json
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, BigInteger, Text, Enum as SAEnum, Float, Index, create_engine
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session

from pica.config import Config

Base = declarative_base()


class ImageStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class Image(Base):
    __tablename__ = "images"

    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(512), nullable=False)
    filepath = Column(String(1024), nullable=False)
    md5_hash = Column(String(32), unique=True, nullable=False, index=True)
    file_size = Column(BigInteger, default=0)
    width = Column(Integer)
    height = Column(Integer)
    status = Column(SAEnum(ImageStatus), default=ImageStatus.PENDING, index=True)
    suggested_category = Column(Text)
    suggested_tags = Column(Text)
    confirmed_category = Column(Text)
    confirmed_tags = Column(Text)
    ai_model = Column(String(64))
    ai_latency_ms = Column(Float)
    pending_path = Column(String(1024))
    archive_path = Column(String(1024))
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    ai_at = Column(DateTime)
    confirmed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("idx_status_created", "status", "created_at"),
    )

    @property
    def suggested_category_list(self) -> list:
        if self.suggested_category:
            return json.loads(self.suggested_category)
        return []

    @property
    def suggested_tags_list(self) -> list:
        if self.suggested_tags:
            return json.loads(self.suggested_tags)
        return []

    @property
    def confirmed_category_list(self) -> list:
        if self.confirmed_category:
            return json.loads(self.confirmed_category)
        return []

    @property
    def confirmed_tags_list(self) -> list:
        if self.confirmed_tags:
            return json.loads(self.confirmed_tags)
        return []

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "filename": self.filename,
            "md5_hash": self.md5_hash,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "status": self.status.value if self.status else None,
            "suggested_category": self.suggested_category_list,
            "suggested_tags": self.suggested_tags_list,
            "confirmed_category": self.confirmed_category_list,
            "confirmed_tags": self.confirmed_tags_list,
            "ai_model": self.ai_model,
            "ai_latency_ms": self.ai_latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ai_at": self.ai_at.isoformat() if self.ai_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
        }

    def __repr__(self):
        return f"<Image(id={self.id}, filename={self.filename}, status={self.status})>"


class ScanStatus(Base):
    __tablename__ = "scan_status"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def get_engine(cfg: Config):
    return create_engine(
        f"sqlite:///{cfg.db_path}",
        echo=False,
        connect_args={"check_same_thread": False},
    )


def init_db(cfg: Config):
    cfg.ensure_dirs()
    engine = get_engine(cfg)
    Base.metadata.create_all(engine)
    return engine


def get_session_factory(engine):
    return sessionmaker(bind=engine)


def get_session(cfg: Config) -> Session:
    engine = get_engine(cfg)
    return sessionmaker(bind=engine)()
