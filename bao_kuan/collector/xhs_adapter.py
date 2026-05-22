from __future__ import annotations

import os
import random

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import AbstractAdapter, NormalizedPost


class XiaohongshuAdapter(AbstractAdapter):
    """XHS adapter skeleton.

    TODO: replace the placeholder endpoint with an approved official API or a compliant internal
    data provider. The HTTP fallback shows retry + UA rotation shape only and returns [] by default.
    """

    platform_name = "小红书"

    def __init__(self) -> None:
        self.api_key = os.getenv("XHS_API_KEY", "")
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        ]

    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        if self.api_key:
            return self._fetch_with_api(niche=niche, limit=limit)
        return self._fetch_with_http(niche=niche, limit=limit)

    def _fetch_with_api(self, niche: str, limit: int) -> list[NormalizedPost]:
        # TODO: map official/provider response into NormalizedPost.
        return []

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def _fetch_with_http(self, niche: str, limit: int) -> list[NormalizedPost]:
        headers = {"User-Agent": random.choice(self.user_agents)}
        # Placeholder request to demonstrate retry + UA rotation; avoid scraping unknown pages in demo.
        with httpx.Client(headers=headers, timeout=10) as _client:
            return []
