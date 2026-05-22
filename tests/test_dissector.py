from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from bao_kuan.dissector import Dissector
from bao_kuan.models import Base, Dissection, Post
from bao_kuan.collector import dedupe_hash


class FakeLLM:
    def __init__(self, responses: list[dict[str, Any]]):
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def chat_json(self, messages, temperature=0.2):
        self.calls.append({"messages": messages, "temperature": temperature})
        if not self.responses:
            raise RuntimeError("no fake responses left")
        return self.responses.pop(0)


def make_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)()


def make_post(session):
    post = Post(
        platform="mock",
        title="独立开发失败不是产品问题",
        opening_text="很多人以为失败是产品不够好，其实是验证太晚。",
        interaction_data={"likes": 100, "comments": 20, "shares": 5, "collects": 30},
        top_comments=["失败后怎么办？", "求模板", "成本多少？"],
        url="https://example.com/a",
        dedupe_hash=dedupe_hash("https://example.com/a", "独立开发失败不是产品问题"),
        published_at=datetime.now(timezone.utc),
        collected_at=datetime.now(timezone.utc),
        raw_meta={},
    )
    session.add(post)
    session.commit()
    return post


def test_dissector_runs_exactly_five_llm_calls():
    session = make_session()
    post = make_post(session)
    fake = FakeLLM([
        {"insufficient_evidence": False, "angles": ["反共识"], "reason": "反常识"},
        {"insufficient_evidence": False, "emotion_trigger": "好奇", "trigger_sentence": "x", "why_it_works": "y"},
        {"insufficient_evidence": False, "structure_steps": ["断言", "证据"], "abstract_pattern": "断言→证据"},
        {"insufficient_evidence": False, "reader_needs": [{"need": "模板", "evidence": ["求模板"]}]},
        {"insufficient_evidence": False, "dark_sides": ["失败后怎么办"], "reasoning": "评论追问"},
    ])
    result = Dissector(llm_client=fake).dissect_post(session, post)

    assert result.status == "completed"
    assert len(fake.calls) == 5
    assert all(call["temperature"] == 0.2 for call in fake.calls)
    assert result.step5_dark_sides["dark_sides"] == ["失败后怎么办"]


def test_dissector_persists_insufficient_evidence_payload():
    session = make_session()
    post = make_post(session)
    fake = FakeLLM([
        {"insufficient_evidence": True, "reason": "标题太短"},
        {"insufficient_evidence": True, "reason": "开头不足"},
        {"insufficient_evidence": True, "reason": "正文不足"},
        {"insufficient_evidence": True, "reason": "评论不足"},
        {"insufficient_evidence": True, "reason": "无法反推"},
    ])
    result = Dissector(llm_client=fake).dissect_post(session, post)

    assert result.status == "completed"
    assert result.step1_angle["insufficient_evidence"] is True
    assert result.step4_comment_needs["reason"] == "评论不足"


def test_dissector_failure_does_not_raise_and_marks_failed():
    session = make_session()
    post = make_post(session)
    fake = FakeLLM([
        {"insufficient_evidence": False, "angles": ["反共识"], "reason": "反常识"},
    ])
    result = Dissector(llm_client=fake).dissect_post(session, post)

    assert result.status == "failed"
    assert "no fake responses left" in (result.error_message or "")
    saved = session.query(Dissection).filter(Dissection.post_id == post.id).one()
    assert saved.step1_angle["angles"] == ["反共识"]
