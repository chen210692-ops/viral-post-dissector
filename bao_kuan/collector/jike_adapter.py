from __future__ import annotations

from .base import AbstractAdapter, NormalizedPost


class JikeAdapter(AbstractAdapter):
    """Jike adapter placeholder.

    TODO: wire an approved API/data-provider source. Kept intentionally thin to avoid fake scraping.
    """

    platform_name = "即刻"

    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        return []
