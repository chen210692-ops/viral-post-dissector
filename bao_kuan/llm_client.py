from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

load_dotenv()

LOGGER = logging.getLogger(__name__)
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


class LLMClient:
    """OpenAI-compatible chat.completions wrapper used by all agents.

    The wrapper intentionally uses `chat.completions.create` instead of the Responses API so that
    OpenAI-compatible domestic services can be swapped in by changing `.env` only.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        chat_model: str | None = None,
        embedding_model: str | None = None,
        mock_mode: bool | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        self.chat_model = chat_model or os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
        self.embedding_model = embedding_model or os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
        self.mock_mode = (
            os.getenv("MOCK_MODE", "false").lower() == "true" if mock_mode is None else mock_mode
        )
        self._client: Any | None = None
        Path("logs").mkdir(exist_ok=True)

    @property
    def client(self) -> Any:
        """Lazy import OpenAI so mock mode can run without network or key."""
        if self._client is None:
            if not self.api_key:
                raise RuntimeError("OPENAI_API_KEY is required when MOCK_MODE=false")
            from openai import OpenAI

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    @retry(
        retry=retry_if_exception_type(Exception),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def chat(self, messages: list[dict[str, str]], temperature: float = 0.2) -> str:
        """Call the chat model and return text content; retry transient failures."""
        if self.mock_mode:
            content = self._mock_chat(messages)
            self._log_usage(prompt_tokens=0, completion_tokens=0, total_tokens=0, mock=True)
            return content

        response = self.client.chat.completions.create(
            model=self.chat_model,
            messages=messages,
            temperature=temperature,
        )
        usage = getattr(response, "usage", None)
        self._log_usage(
            prompt_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            total_tokens=getattr(usage, "total_tokens", 0) if usage else 0,
            mock=False,
        )
        return response.choices[0].message.content or ""

    def chat_json(self, messages: list[dict[str, str]], temperature: float = 0.2) -> dict[str, Any]:
        """Call chat and parse a JSON object from either raw JSON or fenced JSON."""
        content = self.chat(messages=messages, temperature=temperature)
        try:
            return self._extract_json(content)
        except json.JSONDecodeError:
            LOGGER.exception("LLM returned non-JSON content: %s", content[:500])
            return {"insufficient_evidence": True, "raw_text": content, "error": "invalid_json"}

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return embeddings using OpenAI embeddings or deterministic local mock vectors."""
        if not texts:
            return []
        if self.mock_mode or not self.api_key:
            return [self._hash_embedding(text) for text in texts]
        response = self.client.embeddings.create(model=self.embedding_model, input=texts)
        return [item.embedding for item in response.data]

    def _log_usage(self, prompt_tokens: int, completion_tokens: int, total_tokens: int, mock: bool) -> None:
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "model": self.chat_model,
            "base_url": self.base_url,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "mock": mock,
        }
        with Path("logs/llm_usage.log").open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        LOGGER.info("LLM usage: %s", record)

    @staticmethod
    def _extract_json(content: str) -> dict[str, Any]:
        fenced = re.search(r"```json\s*(.*?)```", content, flags=re.S)
        if fenced:
            content = fenced.group(1)
        return json.loads(content.strip())

    @staticmethod
    def _hash_embedding(text: str, dim: int = 64) -> list[float]:
        """Stable local vectors keep clustering runnable in mock/CI without extra models."""
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        values: list[float] = []
        while len(values) < dim:
            digest = hashlib.sha256(digest).digest()
            values.extend([(byte - 128) / 128 for byte in digest])
        return values[:dim]

    def _mock_chat(self, messages: list[dict[str, str]]) -> str:
        joined = "\n".join(m.get("content", "") for m in messages)
        # Prefer explicit prompt task headers. Extra context may contain prior-step JSON keys such as
        # "emotion_trigger", so loose keyword matching would misclassify later steps.
        if "# 任务：暗面挖掘" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "dark_sides": [
                        "产品冷启动失败后的止损标准和复盘模板",
                        "独立开发真实成本、现金流压力与收入波动",
                        "第一批用户不是从社媒来时的替代获客路径",
                    ],
                    "reasoning": "评论追问集中在失败、成本和冷启动，而原内容主要讲成功路径。",
                },
                ensure_ascii=False,
            )
        if "# 任务：评论区真实需求挖掘" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "reader_needs": [
                        {"need": "想要真实收入和成本区间", "evidence": ["能不能公开一下收入？", "服务器和推广花了多少？"]},
                        {"need": "想知道失败后如何止损", "evidence": ["做了三个月没用户怎么办？"]},
                        {"need": "需要可执行的冷启动渠道", "evidence": ["第一批种子用户去哪找？"]},
                    ],
                },
                ensure_ascii=False,
            )
        if "# 任务：结构骨架还原" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "structure_steps": [
                        "反共识断言",
                        "给出失败场景",
                        "拆出关键变量",
                        "提供验证清单",
                        "用评论区问题收尾",
                    ],
                    "abstract_pattern": "反共识断言 → 失败证据 → 方法框架 → 行动清单",
                },
                ensure_ascii=False,
            )
        if "# 任务：情绪钩子定位" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "emotion_trigger": "好奇 + 恐惧",
                    "trigger_sentence": "很多人以为独立开发失败是产品不够好，其实是验证问题太晚。",
                    "why_it_works": "它同时制造认知落差和损失厌恶，让读者想确认自己是否也踩坑。",
                },
                ensure_ascii=False,
            )
        if "# 任务：选题角度归类" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "angles": ["反共识", "教程干货"],
                    "reason": "内容用一个反直觉结论打破读者预期，并承诺给出可复用的方法步骤。",
                },
                ensure_ascii=False,
            )
        if "# 任务：选题顾问" in joined:
            if "真实成本" in joined or "现金流" in joined:
                payload = {
                    "insufficient_evidence": False,
                    "fit_score": 89,
                    "title_options": [
                        "独立开发真实成本表：我到底花了多少钱？",
                        "别只看收入截图：一个小产品的现金流压力",
                        "独立开发最贵的不是服务器，是这 4 个隐性成本",
                        "月入之前，先算清这张成本账",
                        "我把独立开发的时间成本和现金成本摊开讲",
                    ],
                    "angle": "用透明账本切入，把成功叙事背后的现金流、时间和机会成本摊开。",
                    "predicted_interaction_range": {"low": 1600, "high": 6200, "basis": "成本缺口强度高，评论区常追问真实数字"},
                    "writing_points": ["列出固定成本、推广成本和试错成本", "展示收入波动而非单月高点", "说明哪些成本可省、哪些不能省", "给读者一张预算表"],
                    "risks": ["数字不够真实会被质疑炫耀或卖惨", "只讲成本不讲决策会变成流水账"],
                }
            elif "替代获客" in joined or "第一批用户" in joined:
                payload = {
                    "insufficient_evidence": False,
                    "fit_score": 86,
                    "title_options": [
                        "没有个人品牌，第一批用户还能从哪来？",
                        "别只发朋友圈：独立产品冷启动的 7 个替代渠道",
                        "我不用社媒涨粉，也找到第一批种子用户",
                        "从 0 用户开始：一份冷启动渠道实验清单",
                        "独立开发冷启动失败后，换渠道还是换需求？",
                    ],
                    "angle": "避开泛泛增长技巧，按渠道列出适用条件、话术和失败信号。",
                    "predicted_interaction_range": {"low": 1400, "high": 5600, "basis": "冷启动问题广泛，但需要具体案例支撑"},
                    "writing_points": ["区分社群、私信、SEO、工具目录和合作渠道", "给出每个渠道的最低可行动作", "说明什么数据代表渠道无效", "补充无个人品牌时的话术模板"],
                    "risks": ["写成渠道罗列会缺少可信度", "过度承诺容易变成增长玄学"],
                }
            else:
                payload = {
                    "insufficient_evidence": False,
                    "fit_score": 87,
                    "title_options": [
                        "独立开发失败 90 天：什么时候该停手？",
                        "别再优化产品了：冷启动失败的 5 个止损信号",
                        "我用一张表判断项目要不要继续做",
                        "独立开发最贵的不是服务器，是不愿承认没人要",
                        "从 0 用户到放弃：一份诚实复盘模板",
                    ],
                    "angle": "用反共识切入，把“坚持就是胜利”改写成“会止损才是能力”，并给出判断表。",
                    "predicted_interaction_range": {"low": 1800, "high": 6800, "basis": "参考缺口强度与同类 mock 爆款互动"},
                    "writing_points": ["先给出一个明确止损阈值，例如连续 30 天无有效访谈转化", "拆成本：时间、机会成本、现金流、情绪消耗", "提供可复制的复盘表格字段", "区分“该换渠道”与“该关项目”的判断标准"],
                    "risks": ["写得太丧会变成情绪劝退，缺少建设性", "如果没有案例，会像空泛鸡汤的反面版本"],
                }
            return json.dumps(payload, ensure_ascii=False)
        if "选题角度归类" in joined or "angle_categories" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "angles": ["反共识", "教程干货"],
                    "reason": "内容用一个反直觉结论打破读者预期，并承诺给出可复用的方法步骤。",
                },
                ensure_ascii=False,
            )
        if "情绪钩子定位" in joined or "emotion_trigger" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "emotion_trigger": "好奇 + 恐惧",
                    "trigger_sentence": "很多人以为独立开发失败是产品不够好，其实是验证问题太晚。",
                    "why_it_works": "它同时制造认知落差和损失厌恶，让读者想确认自己是否也踩坑。",
                },
                ensure_ascii=False,
            )
        if "结构骨架还原" in joined or "structure_steps" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "structure_steps": [
                        "反共识断言",
                        "给出失败场景",
                        "拆出关键变量",
                        "提供验证清单",
                        "用评论区问题收尾",
                    ],
                    "abstract_pattern": "反共识断言 → 失败证据 → 方法框架 → 行动清单",
                },
                ensure_ascii=False,
            )
        if ("评论区真实需求挖掘" in joined or "reader_needs" in joined) and "暗面挖掘" not in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "reader_needs": [
                        {"need": "想要真实收入和成本区间", "evidence": ["能不能公开一下收入？", "服务器和推广花了多少？"]},
                        {"need": "想知道失败后如何止损", "evidence": ["做了三个月没用户怎么办？"]},
                        {"need": "需要可执行的冷启动渠道", "evidence": ["第一批种子用户去哪找？"]},
                    ],
                },
                ensure_ascii=False,
            )
        if "暗面挖掘" in joined or "dark_sides" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "dark_sides": [
                        "产品冷启动失败后的止损标准和复盘模板",
                        "独立开发真实成本、现金流压力与收入波动",
                        "第一批用户不是从社媒来时的替代获客路径",
                    ],
                    "reasoning": "评论追问集中在失败、成本和冷启动，而原内容主要讲成功路径。",
                },
                ensure_ascii=False,
            )
        if "选题顾问" in joined or "topic_advisor" in joined:
            return json.dumps(
                {
                    "insufficient_evidence": False,
                    "fit_score": 87,
                    "title_options": [
                        "独立开发失败 90 天：什么时候该停手？",
                        "别再优化产品了：冷启动失败的 5 个止损信号",
                        "我用一张表判断项目要不要继续做",
                        "独立开发最贵的不是服务器，是不愿承认没人要",
                        "从 0 用户到放弃：一份诚实复盘模板",
                    ],
                    "angle": "用反共识切入，把“坚持就是胜利”改写成“会止损才是能力”，并给出判断表。",
                    "predicted_interaction_range": {"low": 1800, "high": 6800, "basis": "参考缺口强度与同类 mock 爆款互动"},
                    "writing_points": [
                        "先给出一个明确止损阈值，例如连续 30 天无有效访谈转化",
                        "拆成本：时间、机会成本、现金流、情绪消耗",
                        "提供可复制的复盘表格字段",
                        "区分“该换渠道”与“该关项目”的判断标准",
                    ],
                    "risks": [
                        "写得太丧会变成情绪劝退，缺少建设性",
                        "如果没有案例，会像空泛鸡汤的反面版本",
                    ],
                },
                ensure_ascii=False,
            )
        if "内容缺口摘要专家" in joined:
            if "真实成本" in joined or "现金流" in joined:
                theme = "独立开发真实成本、现金流压力与收入波动"
            elif "替代获客" in joined or "第一批用户" in joined:
                theme = "非社媒路径下的第一批用户获取方法"
            else:
                theme = "产品冷启动失败后的止损标准和复盘模板"
            return json.dumps({"theme": theme, "summary": "读者想看成功叙事背后的失败处理方案。"}, ensure_ascii=False)
        return json.dumps({"insufficient_evidence": True, "reason": "mock client did not match prompt"}, ensure_ascii=False)
