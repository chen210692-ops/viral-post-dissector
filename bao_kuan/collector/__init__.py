from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime
from typing import Iterable

from sqlalchemy.orm import Session

from bao_kuan.models import Post

from .base import AbstractAdapter, NormalizedPost
from .bilibili_adapter import BilibiliAdapter
from .jike_adapter import JikeAdapter
from .mock_adapter import MockAdapter
from .twitter_adapter import TwitterAdapter
from .xhs_adapter import XiaohongshuAdapter

LOGGER = logging.getLogger(__name__)

ADAPTERS: dict[str, type[AbstractAdapter]] = {
    "xhs": XiaohongshuAdapter,
    "小红书": XiaohongshuAdapter,
    "bilibili": BilibiliAdapter,
    "b站": BilibiliAdapter,
    "jike": JikeAdapter,
    "即刻": JikeAdapter,
    "x": TwitterAdapter,
    "twitter": TwitterAdapter,
    "x/twitter": TwitterAdapter,
}


def dedupe_hash(url: str, title: str) -> str:
    """Stable dedupe hash based on URL + title, the most reliable cross-platform fields."""
    return hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()


def _parse_platforms(platforms: str | Iterable[str] | None) -> list[str]:
    if platforms is None:
        return ["xhs", "bilibili"]
    if isinstance(platforms, str):
        return [p.strip().lower() for p in platforms.split(",") if p.strip()]
    return [str(p).strip().lower() for p in platforms if str(p).strip()]


def build_adapters(platforms: str | Iterable[str] | None = None) -> list[AbstractAdapter]:
    """Return platform adapters; mock mode uses one adapter so demo always returns exactly 8 rows."""
    if os.getenv("MOCK_MODE", "false").lower() == "true":
        return [MockAdapter()]
    adapters: list[AbstractAdapter] = []
    for name in _parse_platforms(platforms):
        adapter_cls = ADAPTERS.get(name)
        if adapter_cls:
            adapters.append(adapter_cls())
        else:
            LOGGER.warning("Unknown platform adapter ignored: %s", name)
    return adapters or [XiaohongshuAdapter(), BilibiliAdapter()]


def save_posts(session: Session, posts: list[NormalizedPost]) -> list[Post]:
    """Insert normalized posts into SQLite and skip duplicates."""
    saved: list[Post] = []
    for item in posts:
        dh = dedupe_hash(item.url, item.title)
        existing = session.query(Post).filter(Post.dedupe_hash == dh).one_or_none()
        if existing:
            saved.append(existing)
            continue
        post = Post(
            platform=item.platform,
            title=item.title,
            opening_text=item.opening_text,
            interaction_data=item.interaction_data,
            top_comments=item.top_comments,
            url=item.url,
            dedupe_hash=dh,
            published_at=item.published_at,
            collected_at=item.collected_at,
            raw_meta=item.raw_meta,
        )
        session.add(post)
        saved.append(post)
    session.commit()
    return saved


def collect_posts(
    session: Session,
    niche: str,
    platforms: str | Iterable[str] | None = None,
    limit_per_adapter: int = 20,
) -> list[Post]:
    """Run collection across adapters; adapter failures are logged and isolated."""
    normalized: list[NormalizedPost] = []
    for adapter in build_adapters(platforms):
        try:
            normalized.extend(adapter.fetch(niche=niche, limit=limit_per_adapter))
        except Exception as exc:  # noqa: BLE001 - one platform failure should not kill pipeline.
            LOGGER.exception("Adapter %s failed: %s", adapter.platform_name, exc)
    saved = save_posts(session, normalized)
    LOGGER.info("Collected %s normalized posts at %s", len(saved), datetime.utcnow().isoformat())
    return saved
