from __future__ import annotations

from datetime import datetime
from pathlib import Path

import click
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy.orm import Session

from bao_kuan.clusterer import Clusterer
from bao_kuan.collector import collect_posts
from bao_kuan.dissector import Dissector
from bao_kuan.models import GapCluster, Post, TopicAdvice, init_db, session_scope
from bao_kuan.topic_advisor import TopicAdvisor


def parse_days(value: str) -> int:
    """Parse CLI durations like 7d into day count."""
    value = value.strip().lower()
    if value.endswith("d"):
        return int(value[:-1])
    return int(value)


def run_collect(session: Session, niche: str, platforms: str, limit: int) -> list[Post]:
    return collect_posts(session=session, niche=niche, platforms=platforms, limit_per_adapter=limit)


def run_dissect(session: Session, since_days: int) -> list:
    return Dissector().dissect_recent(session=session, since_days=since_days)


def run_cluster(session: Session, window_days: int) -> list[GapCluster]:
    return Clusterer().cluster_dark_sides(session=session, window_days=window_days)


def run_advise(session: Session, profile: str) -> list[TopicAdvice]:
    return TopicAdvisor().advise(session=session, profile_path=profile, top_k=3)


def render_daily_report(
    session: Session,
    niche: str,
    window_days: int,
    report_date: str | None = None,
) -> Path:
    """Render Markdown daily report using latest DB rows."""
    report_date = report_date or datetime.now().strftime("%Y-%m-%d")
    reports_dir = Path("reports")
    reports_dir.mkdir(exist_ok=True)
    env = Environment(
        loader=FileSystemLoader(str(Path(__file__).parent / "templates")),
        autoescape=select_autoescape(enabled_extensions=()),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("daily_report.md.j2")
    posts = session.query(Post).order_by(Post.collected_at.desc()).limit(8).all()
    gaps = session.query(GapCluster).order_by(GapCluster.strength_score.desc()).limit(10).all()
    advices = session.query(TopicAdvice).order_by(TopicAdvice.fit_score.desc()).limit(3).all()
    output = template.render(
        date=report_date,
        niche=niche,
        window_days=window_days,
        posts=posts,
        gaps=gaps,
        advices=advices,
    )
    path = reports_dir / f"{report_date}-daily.md"
    path.write_text(output, encoding="utf-8")
    return path


@click.group()
def cli() -> None:
    """爆款反向拆解 + 选题预判 CLI."""
    init_db()


@cli.command()
@click.option("--niche", required=True, help="赛道关键词，如：独立开发")
@click.option("--platforms", default="xhs,bilibili", show_default=True, help="逗号分隔平台名")
@click.option("--limit", default=20, show_default=True, help="每个平台最多采集条数")
def collect(niche: str, platforms: str, limit: int) -> None:
    """Run collector once."""
    with session_scope() as session:
        posts = run_collect(session, niche=niche, platforms=platforms, limit=limit)
        click.echo(f"collected={len(posts)}")


@cli.command()
@click.option("--since", default="7d", show_default=True, help="拆解最近 N 天未完成内容")
def dissect(since: str) -> None:
    """Dissect recent posts."""
    with session_scope() as session:
        results = run_dissect(session, since_days=parse_days(since))
        completed = sum(1 for item in results if item.status == "completed")
        click.echo(f"dissected={len(results)} completed={completed}")


@cli.command(name="cluster")
@click.option("--window", default="7d", show_default=True, help="聚类过去 N 天暗面需求")
def cluster_cmd(window: str) -> None:
    """Cluster dark-side needs."""
    with session_scope() as session:
        clusters = run_cluster(session, window_days=parse_days(window))
        click.echo(f"clusters={len(clusters)}")


@cli.command()
@click.option("--profile", default="profiles/my_profile.md", show_default=True, help="人设档案路径")
def advise(profile: str) -> None:
    """Generate topic advice."""
    with session_scope() as session:
        advices = run_advise(session, profile=profile)
        click.echo(f"advices={len(advices)}")
        for idx, item in enumerate(advices, 1):
            first_title = item.title_options[0] if item.title_options else "未命名选题"
            click.echo(f"{idx}. {first_title}")


@cli.command()
@click.option("--niche", default="独立开发", show_default=True, help="赛道关键词")
@click.option("--platforms", default="xhs,bilibili", show_default=True, help="逗号分隔平台名")
@click.option("--profile", default="profiles/my_profile.md", show_default=True, help="人设档案路径")
@click.option("--window", default="7d", show_default=True, help="日报分析窗口")
def daily(niche: str, platforms: str, profile: str, window: str) -> None:
    """Run full pipeline and render daily report."""
    days = parse_days(window)
    with session_scope() as session:
        posts = run_collect(session, niche=niche, platforms=platforms, limit=20)
        dissections = run_dissect(session, since_days=days)
        clusters = run_cluster(session, window_days=days)
        advices = run_advise(session, profile=profile)
        report_path = render_daily_report(session, niche=niche, window_days=days)
        click.echo(
            f"daily_done posts={len(posts)} dissections={len(dissections)} "
            f"clusters={len(clusters)} advices={len(advices)} report={report_path}"
        )
