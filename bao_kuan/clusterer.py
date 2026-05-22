from __future__ import annotations

import logging
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from bao_kuan.llm_client import LLMClient
from bao_kuan.models import Dissection, GapCluster, Post

LOGGER = logging.getLogger(__name__)


class Clusterer:
    """Cluster dark-side needs into unmet content gaps."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()

    def cluster_dark_sides(self, session: Session, window_days: int = 7) -> list[GapCluster]:
        """Cluster all dark-side needs from completed dissections in the given window."""
        rows = self._load_dark_sides(session, window_days=window_days)
        if not rows:
            LOGGER.warning("No dark-side needs found for clustering")
            return []

        texts = [row["text"] for row in rows]
        embeddings = np.asarray(self.llm.embed_texts(texts), dtype=float)
        labels = self._cluster_labels(embeddings)

        grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for label, row in zip(labels, rows):
            grouped[int(label)].append(row)

        raw_scores: dict[int, float] = {}
        for label, items in grouped.items():
            avg_interaction = float(np.mean([item["interaction_score"] for item in items]))
            raw_scores[label] = len(items) * avg_interaction
        max_score = max(raw_scores.values()) if raw_scores else 1.0

        # Rebuild current window output to keep the latest daily report easy to read.
        session.query(GapCluster).filter(GapCluster.window_days == window_days).delete()
        session.commit()

        clusters: list[GapCluster] = []
        for label, items in sorted(grouped.items(), key=lambda kv: raw_scores[kv[0]], reverse=True):
            samples = [item["text"] for item in items[:3]]
            theme = self._summarize_theme(samples)
            strength = round((raw_scores[label] / max_score) * 100, 2) if max_score else 0.0
            cluster = GapCluster(
                window_days=window_days,
                cluster_label=label,
                theme=theme,
                frequency=len(items),
                samples=samples,
                strength_score=strength,
                raw_meta={
                    "raw_score": raw_scores[label],
                    "post_ids": sorted({item["post_id"] for item in items}),
                    "avg_interaction": round(float(np.mean([i["interaction_score"] for i in items])), 2),
                },
            )
            session.add(cluster)
            clusters.append(cluster)
        session.commit()
        return clusters

    def _load_dark_sides(self, session: Session, window_days: int) -> list[dict[str, Any]]:
        threshold = datetime.now(timezone.utc) - timedelta(days=window_days)
        query = (
            session.query(Dissection, Post)
            .join(Post, Dissection.post_id == Post.id)
            .filter(Dissection.status == "completed", Post.published_at >= threshold)
        )
        rows: list[dict[str, Any]] = []
        for dissection, post in query.all():
            for text in self._extract_dark_side_texts(dissection.step5_dark_sides):
                rows.append(
                    {
                        "text": text,
                        "post_id": post.id,
                        "interaction_score": self._interaction_score(post.interaction_data or {}),
                    }
                )
        return rows

    @staticmethod
    def _extract_dark_side_texts(payload: dict[str, Any] | None) -> list[str]:
        if not payload:
            return []
        items = payload.get("dark_sides") or payload.get("items") or []
        texts: list[str] = []
        for item in items:
            if isinstance(item, str):
                texts.append(item)
            elif isinstance(item, dict):
                text = item.get("topic") or item.get("need") or item.get("text")
                if text:
                    texts.append(str(text))
        return texts

    @staticmethod
    def _interaction_score(data: dict[str, int | None]) -> float:
        """Weighted engagement: comments/collects usually imply stronger demand than likes."""
        likes = data.get("likes") or 0
        comments = data.get("comments") or 0
        shares = data.get("shares") or 0
        collects = data.get("collects") or data.get("favorites") or 0
        return float(likes + comments * 3 + shares * 2 + collects * 2)

    @staticmethod
    def _cluster_labels(embeddings: np.ndarray) -> list[int]:
        if len(embeddings) < 3:
            return [0 for _ in range(len(embeddings))]
        try:
            import hdbscan  # type: ignore

            labels = hdbscan.HDBSCAN(min_cluster_size=2, metric="euclidean").fit_predict(embeddings)
        except Exception:  # noqa: BLE001 - fallback makes demo resilient if hdbscan is not installed.
            from sklearn.cluster import DBSCAN
            from sklearn.preprocessing import normalize

            labels = DBSCAN(eps=0.45, min_samples=2, metric="cosine").fit_predict(normalize(embeddings))
        if all(label == -1 for label in labels):
            return [0 for _ in range(len(embeddings))]
        # Treat noise as its own cluster instead of dropping it; niche gaps can be sparse but valuable.
        next_label = max([label for label in labels if label >= 0], default=-1) + 1
        return [next_label if label == -1 else int(label) for label in labels]

    def _summarize_theme(self, samples: list[str]) -> str:
        if not samples:
            return "未命名内容缺口"
        joined = "；".join(samples)
        try:
            result = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": "你是内容缺口摘要专家，只输出 JSON。"},
                    {
                        "role": "user",
                        "content": (
                            "请把以下暗面需求概括成一句中文缺口主题，输出 {\"theme\": \"...\"}。\n"
                            f"样本：{joined}"
                        ),
                    },
                ],
                temperature=0.2,
            )
            return str(result.get("theme") or samples[0])[:200]
        except Exception:  # noqa: BLE001
            LOGGER.exception("Theme summarization failed; fallback to first sample")
            return samples[0][:200]
