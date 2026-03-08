"""
Omada Pulse - 舆情监控 Pipeline 入口
4-stage pipeline: scrape → AI filter → comment fetch → Notion sync
"""
import argparse
import logging
import sys
import os
import signal
import time

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import (
    initialize_configs, monitoring_config, notion_config,
    ai_filter_config, system_config,
)

logger = logging.getLogger("omada_pulse")


def setup_logging(level: str = "INFO"):
    """配置日志"""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def build_pipeline(stages: list[str] = None):
    """Construct all pipeline components from config.
    Only initializes AI filter provider when ai_filter stage is needed.
    """
    from src.db.database import Database
    from src.db.repository import PostRepository
    from src.collectors.reddit_json_collector import RedditJsonCollector
    from src.filters.ai_filter import AIBatchFilter
    from src.pipeline.runner import PipelineRunner

    # Database
    db = Database(db_path=ai_filter_config.db_path)
    repo = PostRepository(db)

    # Reddit collector
    collector = RedditJsonCollector()

    # AI filter — only init provider if needed
    needs_ai = stages is None or "ai_filter" in stages
    ai_filter = None
    if needs_ai and ai_filter_config.api_key:
        if ai_filter_config.provider == "gemini":
            from src.filters.providers import GeminiProvider
            provider = GeminiProvider(
                api_key=ai_filter_config.api_key,
                model=ai_filter_config.model,
            )
        else:
            from src.filters.providers import OpenAICompatibleProvider
            provider = OpenAICompatibleProvider(
                api_key=ai_filter_config.api_key,
                model=ai_filter_config.model,
                base_url=ai_filter_config.base_url or None,
            )
        ai_filter = AIBatchFilter(
            provider=provider,
            relevance_threshold=ai_filter_config.relevance_threshold,
            batch_size=ai_filter_config.batch_size,
        )
    elif needs_ai and not ai_filter_config.api_key:
        logger.warning("AI_FILTER_API_KEY 未配置，跳过 AI 过滤阶段")

    # Notion client (optional)
    notion_client = None
    if notion_config and notion_config.enabled:
        try:
            from src.storage.notion_client import NotionSyncClient
            notion_client = NotionSyncClient()
            logger.info("Notion 客户端已初始化")
        except Exception as e:
            logger.warning(f"Notion 客户端初始化失败: {e}")

    # Pipeline runner
    runner = PipelineRunner(
        repo=repo,
        collector=collector,
        ai_filter=ai_filter,
        notion_client=notion_client,
        subreddits=monitoring_config.target_subreddits,
        max_per_sub=monitoring_config.max_posts_per_subreddit,
        relevance_threshold=ai_filter_config.relevance_threshold,
    )

    return runner, db


def run_single(stages: list[str] = None):
    """单次执行 pipeline"""
    runner, db = build_pipeline(stages=stages)
    try:
        summary = runner.run(stages=stages)
        logger.info(f"Pipeline 完成: {summary}")
        return summary
    finally:
        db.close()


def run_continuous(interval: int = 300):
    """持续运行模式"""
    logger.info(f"进入持续运行模式 (间隔: {interval}s)")
    running = True

    def _stop(signum, frame):
        nonlocal running
        logger.info(f"收到信号 {signum}，准备停止...")
        running = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    while running:
        try:
            summary = run_single()
            logger.info(f"本轮完成: {summary.get('db_status', {})}")
        except Exception as e:
            logger.error(f"Pipeline 执行失败: {e}")

        # 分段等待
        waited = 0
        while waited < interval and running:
            time.sleep(min(10, interval - waited))
            waited += 10

    logger.info("已停止")


def show_stats():
    """显示本地数据库统计"""
    from src.db.database import Database
    from src.db.repository import PostRepository

    db = Database(db_path=ai_filter_config.db_path)
    repo = PostRepository(db)

    counts = repo.get_unprocessed_count()
    total = sum(counts.values())

    print(f"\n📊 本地数据库统计 ({ai_filter_config.db_path})")
    print(f"{'='*40}")
    print(f"  总记录数: {total}")
    for status, count in sorted(counts.items()):
        pct = f"({count/total*100:.1f}%)" if total > 0 else ""
        print(f"  {status}: {count} {pct}")

    # Comments & authors
    comment_count = db.conn.execute("SELECT COUNT(*) FROM comments").fetchone()[0]
    author_count = db.conn.execute("SELECT COUNT(*) FROM authors").fetchone()[0]
    notion_synced = db.conn.execute(
        "SELECT COUNT(*) FROM posts WHERE notion_page_id IS NOT NULL"
    ).fetchone()[0]
    print(f"\n  评论: {comment_count}")
    print(f"  KOL 作者: {author_count}")
    print(f"  Notion 已同步: {notion_synced}")

    # KOL tier breakdown
    tiers = db.conn.execute(
        "SELECT kol_tier, COUNT(*) as cnt FROM authors GROUP BY kol_tier ORDER BY cnt DESC"
    ).fetchall()
    if tiers:
        tier_str = ", ".join(f"{r['kol_tier']}: {r['cnt']}" for r in tiers)
        print(f"  KOL 等级分布: {tier_str}")

    # Recent pipeline runs
    rows = db.conn.execute(
        "SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 10"
    ).fetchall()
    if rows:
        print(f"\n📋 最近 Pipeline 运行记录:")
        for r in rows:
            errors = r["errors"] if r["errors"] else ""
            err_tag = f" ⚠️{errors[:50]}" if errors and errors != "[]" else ""
            print(f"  [{r['stage']:>13}] {r['started_at'][:19]} — "
                  f"处理: {r['posts_processed']}, 通过: {r['posts_passed']}"
                  f"{' model=' + r['model_used'] if r['model_used'] else ''}"
                  f"{err_tag}")

    db.close()


def main():
    parser = argparse.ArgumentParser(
        description="Omada Pulse - Reddit 舆情监控 Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 执行完整 pipeline（采集 → AI过滤 → 抓评论 → 同步Notion）
  python src/main.py

  # 只执行采集和AI过滤（不同步Notion）
  python src/main.py --stages scrape ai_filter

  # 只执行采集
  python src/main.py --stages scrape

  # 持续运行模式
  python src/main.py --mode continuous

  # 查看数据库统计
  python src/main.py --stats

  # 健康检查
  python src/main.py --mode health
        """,
    )
    parser.add_argument(
        "--mode", choices=["single", "continuous", "health"],
        default="single", help="运行模式 (默认: single)",
    )
    parser.add_argument(
        "--stages", nargs="+",
        choices=["scrape", "ai_filter", "comments", "kol", "notion_sync"],
        default=None, help="指定运行的阶段（默认: 全部）",
    )
    parser.add_argument("--stats", action="store_true", help="显示数据库统计")
    parser.add_argument("--interval", type=int, default=300, help="持续模式间隔秒数")
    parser.add_argument("--debug", action="store_true", help="调试模式")

    args = parser.parse_args()

    # Setup
    log_level = "DEBUG" if args.debug else "INFO"
    setup_logging(log_level)
    initialize_configs()

    if args.stats:
        show_stats()
        sys.exit(0)

    if args.mode == "health":
        runner, db = build_pipeline()
        try:
            health = runner.collector.health_check()
            print(f"Reddit 采集器: {health.get('status', 'unknown')}")
            counts = runner.repo.get_unprocessed_count()
            print(f"数据库状态: {counts}")
            if runner.notion_client:
                nh = runner.notion_client.health_check()
                print(f"Notion: {nh.get('status', 'unknown')}")
        finally:
            db.close()
        sys.exit(0)

    if args.mode == "single":
        summary = run_single(stages=args.stages)
        # Exit code based on errors
        has_errors = any(
            isinstance(v, dict) and v.get("error")
            for v in summary.values()
        )
        sys.exit(1 if has_errors else 0)

    elif args.mode == "continuous":
        interval = args.interval or monitoring_config.check_interval
        run_continuous(interval=interval)


if __name__ == "__main__":
    main()
