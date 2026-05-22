from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from bao_kuan.llm_client import LLMClient
from bao_kuan.models import Dissection, Post

LOGGER = logging.getLogger(__name__)

ANGLE_CATEGORIES = [
    "反共识",
    "对比拉踩",
    "亲历叙事",
    "教程干货",
    "情绪宣泄",
    "群体认同",
    "猎奇审丑",
    "权威盖章",
    "反转剧情",
    "低门槛崇拜",
    "高门槛祛魅",
    "时机蹭热",
]

PROMPT_DIR = Path(__file__).parent / "prompts"


class Dissector:
    """Five-step long-chain dissection agent.

    Every step is a separate LLM call and is persisted immediately, making intermediate output
    debuggable and recoverable when later steps fail.
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client or LLMClient()

    def dissect_post(self, session: Session, post: Post) -> Dissection:
        """Run five-step dissection for one post, persisting each step."""
        dissection = session.query(Dissection).filter(Dissection.post_id == post.id).one_or_none()
        if dissection is None:
            dissection = Dissection(post_id=post.id, status="pending")
            session.add(dissection)
            session.commit()

        try:
            post_payload = self._post_payload(post)
            dissection.status = "running"
            dissection.error_message = None
            session.commit()

            dissection.step1_angle = self._run_step(
                prompt_file="dissect_step1_angle.txt",
                post_payload=post_payload,
                extra_context={"angle_categories": ANGLE_CATEGORIES},
            )
            session.commit()

            dissection.step2_hook = self._run_step(
                prompt_file="dissect_step2_hook.txt",
                post_payload=post_payload,
                extra_context={"step1_angle": dissection.step1_angle},
            )
            session.commit()

            dissection.step3_structure = self._run_step(
                prompt_file="dissect_step3_structure.txt",
                post_payload=post_payload,
                extra_context={"step1_angle": dissection.step1_angle, "step2_hook": dissection.step2_hook},
            )
            session.commit()

            dissection.step4_comment_needs = self._run_step(
                prompt_file="dissect_step4_comments.txt",
                post_payload=post_payload,
                extra_context={"step3_structure": dissection.step3_structure},
            )
            session.commit()

            dissection.step5_dark_sides = self._run_step(
                prompt_file="dissect_step5_darkside.txt",
                post_payload=post_payload,
                extra_context={"step4_comment_needs": dissection.step4_comment_needs},
            )
            dissection.status = "completed"
            dissection.updated_at = datetime.now(timezone.utc)
            session.commit()
            return dissection
        except Exception as exc:  # noqa: BLE001 - persist failure and let orchestrator continue.
            LOGGER.exception("Dissection failed for post_id=%s", post.id)
            dissection.status = "failed"
            dissection.error_message = str(exc)
            dissection.updated_at = datetime.now(timezone.utc)
            session.commit()
            return dissection

    def dissect_recent(self, session: Session, since_days: int = 7, limit: int | None = None) -> list[Dissection]:
        """Dissect posts published in the last N days that are not completed yet."""
        threshold = datetime.now(timezone.utc) - timedelta(days=since_days)
        query = session.query(Post).outerjoin(Dissection).filter(Post.published_at >= threshold)
        query = query.filter((Dissection.id.is_(None)) | (Dissection.status != "completed"))
        query = query.order_by(Post.published_at.desc())
        if limit:
            query = query.limit(limit)
        results: list[Dissection] = []
        for post in query.all():
            results.append(self.dissect_post(session, post))
        return results

    def _run_step(self, prompt_file: str, post_payload: dict[str, Any], extra_context: dict[str, Any]) -> dict[str, Any]:
        template = (PROMPT_DIR / prompt_file).read_text(encoding="utf-8")
        user_payload = {
            "post": post_payload,
            "extra_context": extra_context,
        }
        prompt = template.replace("{{INPUT_JSON}}", json.dumps(user_payload, ensure_ascii=False, indent=2))
        messages = [
            {"role": "system", "content": "你是一个严谨的中文内容研究 Agent，只输出合法 JSON。"},
            {"role": "user", "content": prompt},
        ]
        return self.llm.chat_json(messages=messages, temperature=0.2)

    @staticmethod
    def _post_payload(post: Post) -> dict[str, Any]:
        return {
            "platform": post.platform,
            "title": post.title,
            "opening_text": post.opening_text,
            "interaction_data": post.interaction_data,
            "top_comments": post.top_comments,
            "url": post.url,
            "published_at": post.published_at.isoformat() if post.published_at else None,
            "collected_at": post.collected_at.isoformat() if post.collected_at else None,
            "raw_meta": post.raw_meta,
        }
