from __future__ import annotations

import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from dotenv import load_dotenv
from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, sessionmaker

load_dotenv()


def utc_now() -> datetime:
    """Return timezone-aware UTC time for all persisted timestamps."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Post(Base):
    """A normalized popular post collected from any platform."""

    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_posts_dedupe_hash"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    platform: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(512), index=True)
    opening_text: Mapped[str] = mapped_column(Text)
    interaction_data: Mapped[dict] = mapped_column(JSON, default=dict)
    top_comments: Mapped[list] = mapped_column(JSON, default=list)
    url: Mapped[str] = mapped_column(String(1024), index=True)
    dedupe_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)
    raw_meta: Mapped[dict] = mapped_column(JSON, default=dict)

    dissection: Mapped["Dissection | None"] = relationship(
        back_populates="post", cascade="all, delete-orphan", uselist=False
    )


class Dissection(Base):
    """The five-step long-chain dissection result for one post."""

    __tablename__ = "dissections"
    __table_args__ = (UniqueConstraint("post_id", name="uq_dissections_post_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", index=True)

    step1_angle: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step2_hook: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step3_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step4_comment_needs: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    step5_dark_sides: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    post: Mapped[Post] = relationship(back_populates="dissection")


class GapCluster(Base):
    """A cluster of unmet dark-side content needs."""

    __tablename__ = "gap_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    window_days: Mapped[int] = mapped_column(Integer, index=True)
    cluster_label: Mapped[int] = mapped_column(Integer, index=True)
    theme: Mapped[str] = mapped_column(String(512))
    frequency: Mapped[int] = mapped_column(Integer)
    samples: Mapped[list] = mapped_column(JSON, default=list)
    strength_score: Mapped[float] = mapped_column(Float)
    raw_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class TopicAdvice(Base):
    """One suggested topic derived from a gap and a creator profile."""

    __tablename__ = "topic_advices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("gap_clusters.id"), nullable=True)
    title_options: Mapped[list] = mapped_column(JSON, default=list)
    angle: Mapped[str] = mapped_column(Text)
    predicted_interaction_range: Mapped[dict] = mapped_column(JSON, default=dict)
    writing_points: Mapped[list] = mapped_column(JSON, default=list)
    risks: Mapped[list] = mapped_column(JSON, default=list)
    fit_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


_ENGINE = None
_SessionLocal: sessionmaker[Session] | None = None


def _database_url() -> str:
    return os.getenv("DATABASE_URL", "sqlite:///data/posts.db")


def get_engine():
    """Create or return the shared SQLAlchemy engine."""
    global _ENGINE
    if _ENGINE is None:
        url = _database_url()
        if url.startswith("sqlite:///"):
            db_path = Path(url.replace("sqlite:///", ""))
            db_path.parent.mkdir(parents=True, exist_ok=True)
        _ENGINE = create_engine(url, future=True)
    return _ENGINE


def init_db() -> None:
    """Initialize database schema."""
    Base.metadata.create_all(get_engine())


def get_session_factory() -> sessionmaker[Session]:
    """Return a configured Session factory."""
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)
    return _SessionLocal


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session scope."""
    init_db()
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
