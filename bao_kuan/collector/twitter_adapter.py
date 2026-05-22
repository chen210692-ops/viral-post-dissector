from __future__ import annotations

from .base import AbstractAdapter, NormalizedPost


class TwitterAdapter(AbstractAdapter):
    """X/Twitter adapter placeholder.

    TODO: use the official API with TWITTER_BEARER_TOKEN and map tweets/comments into NormalizedPost.
    """

    platform_name = "X/Twitter"

    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        return []
