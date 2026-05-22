from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class NormalizedPost(BaseModel):
    """Cross-platform normalized post schema used before persistence."""

    platform: str
    title: str
    opening_text: str
    interaction_data: dict[str, int | None] = Field(default_factory=dict)
    top_comments: list[str] = Field(default_factory=list)
    url: str
    published_at: datetime
    collected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    raw_meta: dict[str, Any] = Field(default_factory=dict)


class AbstractAdapter(ABC):
    """Minimal adapter interface: fetch normalized posts for a niche keyword."""

    platform_name: str

    @abstractmethod
    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        """Fetch posts from the platform and return normalized records."""
        raise NotImplementedError
