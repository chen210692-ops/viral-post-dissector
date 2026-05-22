from __future__ import annotations

import os
import random

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import AbstractAdapter, NormalizedPost


class BilibiliAdapter(AbstractAdapter):
    """Bilibili adapter skeleton with API-first / HTTP fallback structure."""

    platform_name = "B站"

    def __init__(self) -> None:
        self.api_key = os.getenv("BILIBILI_API_KEY", "")
        self.user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        ]

    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        if self.api_key:
            return self._fetch_with_api(niche=niche, limit=limit)
        return self._fetch_with_http(niche=niche, limit=limit)

    def _fetch_with_api(self, niche: str, limit: int) -> list[NormalizedPost]:
        # TODO: call official/open platform API and normalize response.
        return []

    @retry(wait=wait_exponential(multiplier=1, min=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def _fetch_with_http(self, niche: str, limit: int) -> list[NormalizedPost]:
        headers = {"User-Agent": random.choice(self.user_agents)}
        with httpx.Client(headers=headers, timeout=10) as _client:
            return []
