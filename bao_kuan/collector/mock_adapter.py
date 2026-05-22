from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import md5

from .base import AbstractAdapter, NormalizedPost


class MockAdapter(AbstractAdapter):
    """Eight deterministic posts for full pipeline demos without any API key."""

    platform_name = "mock"

    def fetch(self, niche: str, limit: int = 20) -> list[NormalizedPost]:
        now = datetime.now(timezone.utc)
        titles = [
            f"我用 7 天验证了一个{niche}产品，结果最有用的是这张表",
            f"别再问{niche}怎么变现，先看你有没有这 3 个信号",
            f"一个{niche}项目从 0 到 1 的真实冷启动记录",
            f"做{niche}半年后，我发现流量不是最难的",
            f"为什么很多{niche}教程看完还是没结果",
            f"{niche}独立创作者最容易高估的能力",
            f"我删掉了 80% 功能，{niche}产品反而开始有人买",
            f"如果重新做一次{niche}，我会先访谈 30 个人",
        ]
        openings = [
            f"很多人以为{niche}失败是产品不够好，其实是验证问题太晚。我把最近 7 天的访谈、落地页和转化记录放进一张表，才发现用户根本不是在拒绝价格。",
            f"你现在最该关心的不是怎么收钱，而是谁已经被这个问题折磨到愿意主动找替代方案。没有这 3 个信号，变现讨论大概率是自嗨。",
            f"第一批用户不是发朋友圈来的。我记录了 21 次冷启动尝试，其中真正有效的只有 3 次，而且都和所谓增长技巧没关系。",
            f"做了半年后我才承认：流量不是最难的，最难的是把一个模糊痛点变成别人愿意今天处理的问题。",
            f"大多数教程把过程讲得太顺了，跳过了最难受的部分：没人回你、数据很差、你还要判断是不是方向错了。",
            f"独立创作者最容易高估写作和开发能力，低估销售、分发和持续复盘。这个偏差会让一个好项目死在沉默里。",
            f"删功能前我很害怕，觉得用户会嫌弃。结果保留一个核心任务后，用户终于知道它能帮自己完成什么。",
            f"如果重来一次，我不会先写代码，而是先找 30 个正在用笨办法解决问题的人。访谈比灵感更诚实。",
        ]
        comment_bank = [
            [
                "能不能公开一下收入和成本？",
                "做了三个月没用户怎么办？",
                "第一批种子用户去哪找？",
                "有没有这张验证表模板？",
                "失败的项目最后怎么处理？",
            ],
            [
                "怎么判断是真需求不是伪需求？",
                "B 端和 C 端的信号一样吗？",
                "愿意付费是不是唯一标准？",
                "如果用户说喜欢但不买呢？",
                "冷启动渠道可以展开讲讲吗？",
            ],
            [
                "21 次尝试里失败的 18 次是什么？",
                "你怎么写第一封私信？",
                "没有个人品牌可以做吗？",
                "转化率大概多少算正常？",
                "求完整 SOP。",
            ],
        ]
        posts: list[NormalizedPost] = []
        platforms = ["小红书", "B站", "即刻", "X/Twitter"]
        for i, title in enumerate(titles[: min(limit, 8)]):
            slug = md5(f"{niche}-{i}".encode("utf-8")).hexdigest()[:10]
            comments = (comment_bank[i % len(comment_bank)] * 4)[:20]
            likes = 1200 + i * 870
            comments_count = 180 + i * 43
            shares = 60 + i * 17
            collects = 300 + i * 91
            posts.append(
                NormalizedPost(
                    platform=platforms[i % len(platforms)],
                    title=title,
                    opening_text=openings[i],
                    interaction_data={
                        "likes": likes,
                        "comments": comments_count,
                        "shares": shares,
                        "collects": collects,
                    },
                    top_comments=comments,
                    url=f"https://mock.local/{slug}",
                    published_at=now - timedelta(days=i % 6, hours=i),
                    raw_meta={"mock_index": i, "niche": niche},
                )
            )
        return posts
