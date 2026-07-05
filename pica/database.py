import enum
import json
import logging
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, DateTime, BigInteger, Text, Enum as SAEnum, Float, Index,
    ForeignKey, create_engine, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship

from pica.config import Config

logger = logging.getLogger(__name__)
Base = declarative_base()


class ImageStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class SimilarGroup(Base):
    __tablename__ = "similar_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(256))
    phash_ref = Column(String(64), index=True)
    processed = Column(Integer, default=0)  # 0=unprocessed, 1=processed
    created_at = Column(DateTime, default=datetime.utcnow)

    images = relationship("Image", back_populates="similar_group", foreign_keys="Image.similar_group_id")


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
    ai_status = Column(String(16), default='pending', index=True)
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

    phash = Column(String(64), index=True)
    work_name = Column(String(256))
    image_type = Column(String(64))
    similar_group_id = Column(Integer, ForeignKey("similar_groups.id"), nullable=True, index=True)
    has_text = Column(Integer, default=0)
    extracted_text = Column(Text)

    __table_args__ = (
        Index("idx_status_created", "status", "created_at"),
        Index("idx_phash_status", "phash", "status"),
    )

    similar_group = relationship("SimilarGroup", back_populates="images", foreign_keys=[similar_group_id])
    category_links = relationship("ImageCategory", back_populates="image", cascade="all, delete-orphan")
    tag_links = relationship("ImageTag", back_populates="image", cascade="all, delete-orphan")

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

    @property
    def suggested_categories_rel(self) -> list:
        """List of Category objects suggested by AI."""
        return [link.category for link in self.category_links if link.source == "suggested"]

    @property
    def confirmed_categories_rel(self) -> list:
        """List of Category objects confirmed by user."""
        return [link.category for link in self.category_links if link.source == "confirmed"]

    @property
    def suggested_tags_rel(self) -> list:
        """List of Tag objects suggested by AI."""
        return [link.tag for link in self.tag_links if link.source == "suggested"]

    @property
    def confirmed_tags_rel(self) -> list:
        """List of Tag objects confirmed by user."""
        return [link.tag for link in self.tag_links if link.source == "confirmed"]

    def to_dict(self) -> dict:
        cl = self.category_links
        tl = self.tag_links
        return {
            "id": self.id,
            "filename": self.filename,
            "md5_hash": self.md5_hash,
            "file_size": self.file_size,
            "width": self.width,
            "height": self.height,
            "status": self.status.value if self.status else None,
            "ai_status": self.ai_status,
            "suggested_category": [c.name for c in self.suggested_categories_rel] or self.suggested_category_list,
            "suggested_tags": [t.name for t in self.suggested_tags_rel] or self.suggested_tags_list,
            "confirmed_category": [c.name for c in self.confirmed_categories_rel] or self.confirmed_category_list,
            "confirmed_tags": [t.name for t in self.confirmed_tags_rel] or self.confirmed_tags_list,
            "ai_model": self.ai_model,
            "ai_latency_ms": self.ai_latency_ms,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "ai_at": self.ai_at.isoformat() if self.ai_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "phash": self.phash,
            "work_name": self.work_name,
            "image_type": self.image_type,
            "similar_group_id": self.similar_group_id,
            "has_text": self.has_text,
            "extracted_text": self.extracted_text,
        }

    def __repr__(self):
        return f"<Image(id={self.id}, filename={self.filename}, status={self.status})>"


class Category(Base):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    color = Column(String(7), default="#007AFF")
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    children = relationship("Category", backref="parent", remote_side=[id],
                            order_by="Category.sort_order")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(128), unique=True, nullable=False)
    color = Column(String(7), default="#8E8E93")
    created_at = Column(DateTime, default=datetime.utcnow)


class ImageCategory(Base):
    __tablename__ = "image_categories"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(16), default="suggested", index=True)  # suggested / confirmed

    image = relationship("Image", back_populates="category_links")
    category = relationship("Category")


class ImageTag(Base):
    __tablename__ = "image_tags"

    id = Column(Integer, primary_key=True, autoincrement=True)
    image_id = Column(Integer, ForeignKey("images.id", ondelete="CASCADE"), nullable=False, index=True)
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String(16), default="suggested", index=True)  # suggested / confirmed

    image = relationship("Image", back_populates="tag_links")
    tag = relationship("Tag")


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


def _migrate(engine):
    """Add new columns to existing tables (safe to call repeatedly)."""
    additions = {
        "images": [
            ("phash", "VARCHAR(64)"),
            ("work_name", "VARCHAR(256)"),
            ("image_type", "VARCHAR(64)"),
            ("similar_group_id", "INTEGER REFERENCES similar_groups(id)"),
            ("ai_status", "VARCHAR(16) DEFAULT 'pending'"),
            ("has_text", "INTEGER DEFAULT 0"),
            ("extracted_text", "TEXT"),
        ],
        "similar_groups": [
            ("processed", "INTEGER DEFAULT 0"),
        ],
    }
    with engine.connect() as conn:
        for table, columns in additions.items():
            for col_name, col_type in columns:
                try:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
                    conn.commit()
                    logger.info("migrated: added %s.%s", table, col_name)
                except Exception:
                    conn.rollback()


def _ensure_category(name: str, session: Session) -> Category:
    """Get or create a Category by name."""
    cat = session.query(Category).filter_by(name=name).first()
    if not cat:
        cat = Category(name=name)
        session.add(cat)
        session.flush()
    return cat


def _ensure_tag(name: str, session: Session) -> Tag:
    """Get or create a Tag by name."""
    tag = session.query(Tag).filter_by(name=name).first()
    if not tag:
        tag = Tag(name=name)
        session.add(tag)
        session.flush()
    return tag


def _migrate_json_to_relations(session: Session):
    """Migrate old JSON text fields to new Category/Tag junction tables."""
    count = 0
    images = session.query(Image).filter(
        (Image.suggested_category.isnot(None) & (Image.suggested_category != "[]"))
        | (Image.suggested_tags.isnot(None) & (Image.suggested_tags != "[]"))
        | (Image.confirmed_category.isnot(None) & (Image.confirmed_category != "[]"))
        | (Image.confirmed_tags.isnot(None) & (Image.confirmed_tags != "[]"))
    ).all()
    for img in images:
        changed = False
        # suggested categories
        for name in img.suggested_category_list:
            if not any(link.source == "suggested" for link in img.category_links):
                cat = _ensure_category(name, session)
                img.category_links.append(ImageCategory(category_id=cat.id, source="suggested"))
                changed = True
        # confirmed categories
        for name in img.confirmed_category_list:
            if not any(link.source == "confirmed" for link in img.category_links):
                cat = _ensure_category(name, session)
                img.category_links.append(ImageCategory(category_id=cat.id, source="confirmed"))
                changed = True
        # suggested tags
        for name in img.suggested_tags_list:
            if not any(link.source == "suggested" for link in img.tag_links):
                tag = _ensure_tag(name, session)
                img.tag_links.append(ImageTag(tag_id=tag.id, source="suggested"))
                changed = True
        # confirmed tags
        for name in img.confirmed_tags_list:
            if not any(link.source == "confirmed" for link in img.tag_links):
                tag = _ensure_tag(name, session)
                img.tag_links.append(ImageTag(tag_id=tag.id, source="confirmed"))
                changed = True
        if changed:
            count += 1
    if count:
        session.commit()
        logger.info("migrated category/tag relations for %d images", count)


def init_db(cfg: Config):
    cfg.ensure_dirs()
    engine = get_engine(cfg)
    Base.metadata.create_all(engine)
    _migrate(engine)
    session_factory = get_session_factory(engine)
    with session_factory() as session:
        _migrate_json_to_relations(session)
    return engine


def get_session_factory(engine):
    return sessionmaker(bind=engine)


def get_session(cfg: Config) -> Session:
    engine = get_engine(cfg)
    return sessionmaker(bind=engine)()
