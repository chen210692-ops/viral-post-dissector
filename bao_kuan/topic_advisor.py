from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from bao_kuan.llm_client import LLMClient
from bao_kuan.models import GapCluster, TopicAdvice

LOGGER = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).parent / "prompts" / "topic_advisor.txt"


class TopicAdvisor:
    """Generate topics that fit the creator profile and exploit unmet content gaps."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()

    def advise(self, session: Session, profile_path: str = "profiles/my_profile.md", top_k: int = 3) -> list[TopicAdvice]:
        """Return top-K topic advices based on latest gap clusters."""
        profile = self._read_profile(profile_path)
        gaps = (
            session.query(GapCluster)
            .order_by(GapCluster.created_at.desc(), GapCluster.strength_score.desc())
            .limit(max(top_k * 2, 5))
            .all()
        )
        if not gaps:
            LOGGER.warning("No gap clusters available for topic advice")
            return []

        # Clear old advice for a simple one-report-per-run workflow.
        session.query(TopicAdvice).delete()
        session.commit()

        advice_rows: list[TopicAdvice] = []
        for gap in gaps:
            result = self._advise_one_gap(profile=profile, gap=gap)
            if result.get("insufficient_evidence"):
                continue
            advice = TopicAdvice(
                cluster_id=gap.id,
                title_options=result.get("title_options", [])[:5],
                angle=str(result.get("angle", "")),
                predicted_interaction_range=result.get("predicted_interaction_range", {}),
                writing_points=result.get("writing_points", [])[:5],
                risks=result.get("risks", [])[:2],
                fit_score=float(result.get("fit_score", 0) or 0),
                raw_meta={"gap_theme": gap.theme, "source_gap_strength": gap.strength_score},
            )
            session.add(advice)
            advice_rows.append(advice)
        session.commit()
        return sorted(advice_rows, key=lambda row: row.fit_score or 0, reverse=True)[:top_k]

    def _advise_one_gap(self, profile: str, gap: GapCluster) -> dict[str, Any]:
        template = PROMPT_PATH.read_text(encoding="utf-8")
        payload = {
            "profile": profile,
            "gap": {
                "theme": gap.theme,
                "frequency": gap.frequency,
                "samples": gap.samples,
                "strength_score": gap.strength_score,
                "raw_meta": gap.raw_meta,
            },
        }
        prompt = template.replace("{{INPUT_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2))
        return self.llm.chat_json(
            messages=[
                {"role": "system", "content": "你是选题顾问和创作者定位专家，只输出合法 JSON。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )

    @staticmethod
    def _read_profile(profile_path: str) -> str:
        path = Path(profile_path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        fallback = Path("profiles/my_profile.md.example")
        if fallback.exists():
            return fallback.read_text(encoding="utf-8")
        return "# 默认人设\n独立开发者，关注产品验证、冷启动、真实复盘。"
