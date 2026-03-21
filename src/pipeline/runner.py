"""Multi-source pipeline orchestrator: scrape → AI filter → comment fetch → Notion sync."""
import logging
from datetime import datetime, timezone, timedelta

from src.collectors.reddit_json_collector import RedditJsonCollector
from src.db.repository import PostRepository
from src.filters.ai_filter import AIBatchFilter

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Orchestrates the full data pipeline."""

    def __init__(
        self,
        repo: PostRepository,
        collector: RedditJsonCollector,
        ai_filter: AIBatchFilter,
        notion_client=None,
        subreddits: list[str] = None,
        max_per_sub: int = 100,
        relevance_threshold: float = 0.4,
        youtube_collector=None,
        youtube_repo=None,
        youtube_config=None,
    ):
        self.repo = repo
        self.collector = collector
        self.ai_filter = ai_filter
        self.notion_client = notion_client
        self.subreddits = subreddits or []
        self.max_per_sub = max_per_sub
        self.relevance_threshold = relevance_threshold
        self.yt_collector = youtube_collector
        self.yt_repo = youtube_repo
        self.yt_config = youtube_config

    def run(self, stages: list[str] = None) -> dict:
        """Execute pipeline stages. Default: all stages in order.

        Args:
            stages: list of stage names to run. Options:
                    ['scrape', 'yt_scrape', 'ai_filter', 'comments',
                     'yt_comments', 'kol', 'notion_sync']
                    If None, runs all stages.
        Returns:
            Summary dict with stats for each stage.
        """
        all_stages = ["scrape", "yt_scrape", "ai_filter", "comments",
                       "yt_comments", "kol", "notion_sync"]
        stages = stages or all_stages
        summary = {}

        for stage in stages:
            if stage not in all_stages:
                logger.warning(f"Unknown stage: {stage}, skipping")
                continue

            # Skip YouTube stages if not configured
            if stage.startswith("yt_") and not self.yt_collector:
                logger.debug(f"Skipping {stage}: YouTube not configured")
                continue

            logger.info(f"{'='*60}")
            logger.info(f"STAGE: {stage}")
            logger.info(f"{'='*60}")

            try:
                if stage == "scrape":
                    summary["scrape"] = self.run_stage_scrape()
                elif stage == "yt_scrape":
                    summary["yt_scrape"] = self.run_stage_yt_scrape()
                elif stage == "ai_filter":
                    summary["ai_filter"] = self.run_stage_ai_filter()
                elif stage == "comments":
                    summary["comments"] = self.run_stage_comments()
                elif stage == "yt_comments":
                    summary["yt_comments"] = self.run_stage_yt_comments()
                elif stage == "kol":
                    summary["kol"] = self.run_stage_kol()
                elif stage == "notion_sync":
                    summary["notion_sync"] = self.run_stage_notion_sync()
            except Exception as e:
                logger.error(f"Stage {stage} failed: {e}")
                summary[stage] = {"error": str(e)}

        # Log final status
        counts = self.repo.get_unprocessed_count()
        logger.info(f"Pipeline complete. DB status: {counts}")
        summary["db_status"] = counts
        return summary

    # ------------------------------------------------------------------
    # Stage 1: Scrape
    # ------------------------------------------------------------------

    def run_stage_scrape(self) -> dict:
        """Fetch all new posts from target subreddits into SQLite.

        Includes incremental hot post detection: compares current score/comments
        against previous values and flags posts with significant changes.
        """
        total_new = 0
        total_updated = 0
        total_hot = 0
        errors = []

        for sub in self.subreddits:
            logger.info(f"Scraping r/{sub} ...")
            try:
                posts = self.collector.fetch_subreddit_posts(
                    sub, sort="new", limit=self.max_per_sub
                )
                if not posts:
                    logger.info(f"  r/{sub}: no posts returned")
                    continue

                # Insert new posts
                new_count = self.repo.insert_posts(posts)
                total_new += new_count

                # Update stats for existing posts + detect hot posts
                sub_hot = 0
                for p in posts:
                    is_hot = self.repo.update_post_stats(
                        p["id"], p.get("score", 0), p.get("num_comments", 0)
                    )
                    total_updated += 1
                    if is_hot:
                        sub_hot += 1
                        total_hot += 1
                        logger.info(
                            f"  🔥 热帖检测: {p['id']} "
                            f"(score={p.get('score', 0)}, comments={p.get('num_comments', 0)})"
                        )

                logger.info(
                    f"  r/{sub}: {len(posts)} fetched, {new_count} new, {sub_hot} hot"
                )

            except Exception as e:
                logger.error(f"  r/{sub} scrape failed: {e}")
                errors.append(f"r/{sub}: {e}")

        self.repo.log_pipeline_run("scrape", total_new + total_updated, total_new, errors)
        result = {
            "new_posts": total_new,
            "updated": total_updated,
            "hot_posts": total_hot,
            "errors": errors,
        }
        logger.info(f"Scrape complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Stage: YouTube Scrape
    # ------------------------------------------------------------------

    def run_stage_yt_scrape(self) -> dict:
        """Fetch YouTube videos via channel monitoring + keyword search + stats refresh."""
        if not self.yt_collector or not self.yt_repo:
            logger.warning("YouTube not configured, skipping yt_scrape")
            return {"error": "not_configured"}

        total_new = 0
        total_hot = 0
        errors = []
        quota_used_before = self.yt_repo.get_daily_quota_used()
        quota_limit = self.yt_config.daily_quota_limit if self.yt_config else 10000

        # --- Step 1: Channel monitoring (cheap, 1 unit/channel) ---
        channels = self.yt_repo.get_monitored_channels()
        if not channels:
            # First run: resolve handles and store channels
            if self.yt_config and self.yt_config.monitored_channels:
                logger.info(f"首次运行: 解析 {len(self.yt_config.monitored_channels)} 个频道 handle ...")
                resolved = self.yt_collector.resolve_handles(self.yt_config.monitored_channels)
                for ch in resolved:
                    self.yt_repo.upsert_channel(ch)
                    logger.info(f"  频道已注册: {ch.get('title', '')} ({ch.get('id', '')})")
                channels = self.yt_repo.get_monitored_channels()

        for ch in channels:
            uploads_id = ch.get("uploads_playlist_id", "")
            if not uploads_id:
                continue
            try:
                uploads = self.yt_collector.get_channel_uploads(uploads_id, max_results=10)
                if not uploads:
                    continue

                # Get full details for new videos
                new_ids = []
                for v in uploads:
                    existing = self.yt_repo.db.conn.execute(
                        "SELECT id FROM youtube_videos WHERE id=?", (v["id"],)
                    ).fetchone()
                    if not existing:
                        new_ids.append(v["id"])

                if new_ids:
                    details = self.yt_collector.get_video_details(new_ids)
                    for d in details:
                        d["discovered_via"] = "channel_monitor"
                    inserted = self.yt_repo.insert_videos(details)
                    total_new += inserted
                    logger.info(f"  频道 {ch.get('title', '')}: {inserted} 新视频")

            except Exception as e:
                logger.error(f"  频道 {ch.get('title', '')} 采集失败: {e}")
                errors.append(f"channel:{ch.get('id', '')}: {e}")

        # --- Step 2: Keyword search (expensive, 100 units/query, throttled) ---
        current_quota = self.yt_repo.get_daily_quota_used()
        quota_pct = current_quota / quota_limit if quota_limit > 0 else 1.0

        if quota_pct >= 0.8:
            logger.warning(f"配额已用 {quota_pct:.0%}，跳过关键词搜索")
        elif self.yt_config and self.yt_config.search_keywords:
            for keyword in self.yt_config.search_keywords:
                state = self.yt_repo.get_search_state(keyword)
                if state:
                    last_search = datetime.fromisoformat(state["last_search_at"])
                    hours_since = (datetime.now(timezone.utc) - last_search).total_seconds() / 3600
                    if hours_since < self.yt_config.search_interval_hours:
                        logger.debug(f"  关键词 '{keyword}': 距上次搜索 {hours_since:.1f}h，跳过")
                        continue

                try:
                    # Use publishedAfter for incremental search
                    published_after = None
                    if state and state.get("last_search_at"):
                        published_after = state["last_search_at"]

                    results = self.yt_collector.search_videos(
                        keyword,
                        max_results=self.yt_config.max_search_results,
                        published_after=published_after,
                    )

                    if results:
                        # Get full details
                        search_ids = [v["id"] for v in results]
                        details = self.yt_collector.get_video_details(search_ids)
                        for d in details:
                            d["discovered_via"] = "search"
                        inserted = self.yt_repo.insert_videos(details)
                        total_new += inserted
                        logger.info(f"  搜索 '{keyword}': {len(results)} 结果, {inserted} 新视频")

                    self.yt_repo.update_search_state(keyword, len(results))

                except Exception as e:
                    logger.error(f"  搜索 '{keyword}' 失败: {e}")
                    errors.append(f"search:{keyword}: {e}")

        # --- Step 3: Stats refresh for recent videos (cheap, 1 unit/50 videos) ---
        recent_ids = self.yt_repo.get_recent_video_ids(days=7)
        if recent_ids:
            try:
                details = self.yt_collector.get_video_details(recent_ids)
                hot_jump_cfg = {}
                if self.yt_config:
                    hot_jump_cfg = {
                        "hot_view_jump": self.yt_config.hot_view_jump,
                        "hot_like_jump": self.yt_config.hot_like_jump,
                        "hot_comment_jump": self.yt_config.hot_comment_jump,
                    }
                for d in details:
                    is_hot = self.yt_repo.update_video_stats(
                        d["id"], d.get("view_count", 0),
                        d.get("like_count", 0), d.get("comment_count", 0),
                        **hot_jump_cfg,
                    )
                    if is_hot:
                        total_hot += 1
                        logger.info(
                            f"  🔥 热视频: {d['id']} "
                            f"(views={d.get('view_count', 0)}, likes={d.get('like_count', 0)})"
                        )
                logger.info(f"  统计刷新: {len(details)} 视频, {total_hot} 热视频")
            except Exception as e:
                logger.error(f"  统计刷新失败: {e}")
                errors.append(f"stats_refresh: {e}")

        quota_used_after = self.yt_repo.get_daily_quota_used()
        self.yt_repo.log_pipeline_run("yt_scrape", total_new + len(recent_ids), total_new, errors)
        result = {
            "new_videos": total_new,
            "hot_videos": total_hot,
            "quota_used": quota_used_after - quota_used_before,
            "quota_total": quota_used_after,
            "errors": errors,
        }
        logger.info(f"YouTube scrape complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Stage 2: AI Filter
    # ------------------------------------------------------------------

    def run_stage_ai_filter(self) -> dict:
        """Run AI batch filter on all scraped (unprocessed) posts and YouTube videos."""
        if not self.ai_filter:
            logger.warning("AI filter not configured (missing API key), skipping")
            return {"processed": 0, "filtered": 0, "rejected": 0, "skipped": "no_api_key"}

        # --- Reddit posts ---
        posts = self.repo.get_posts_by_status("scraped")
        total_processed = 0
        total_filtered = 0
        total_rejected = 0

        if posts:
            logger.info(f"AI filtering {len(posts)} Reddit posts ...")
            results = self.ai_filter.filter_all(posts)
            filtered, rejected = self.repo.update_ai_filter_results(
                results, threshold=self.relevance_threshold
            )
            total_processed += len(posts)
            total_filtered += filtered
            total_rejected += rejected

        # --- YouTube videos ---
        if self.yt_repo:
            yt_videos = self.yt_repo.get_videos_by_status("scraped")
            if yt_videos:
                logger.info(f"AI filtering {len(yt_videos)} YouTube videos ...")
                # Add source marker for payload builder
                for v in yt_videos:
                    v["source"] = "youtube"
                yt_results = self.ai_filter.filter_all(yt_videos)
                yt_filtered, yt_rejected = self.yt_repo.update_ai_filter_results(
                    yt_results, threshold=self.relevance_threshold
                )
                total_processed += len(yt_videos)
                total_filtered += yt_filtered
                total_rejected += yt_rejected
                logger.info(f"  YouTube: {yt_filtered} passed, {yt_rejected} rejected")

        self.repo.log_pipeline_run(
            "ai_filter", total_processed, total_filtered,
            model=self.ai_filter.provider.model_name if self.ai_filter else None,
        )

        result = {"processed": total_processed, "filtered": total_filtered, "rejected": total_rejected}
        logger.info(f"AI filter complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Stage 3: Comment Fetch
    # ------------------------------------------------------------------

    def run_stage_comments(self) -> dict:
        """Fetch full comments for posts that passed AI filter."""
        posts = self.repo.get_posts_needing_comments()
        if not posts:
            logger.info("No posts need comment fetching")
            return {"posts_processed": 0, "comments_fetched": 0}

        logger.info(f"Fetching comments for {len(posts)} posts ...")
        total_comments = 0
        errors = []

        for p in posts:
            try:
                result = self.collector.fetch_post_with_comments(p["id"])
                comments = result.get("comments", [])
                # Flatten nested comments for storage
                flat = self._flatten_comments(comments)
                inserted = self.repo.insert_comments(p["id"], flat)
                total_comments += inserted
                logger.debug(f"  Post {p['id']}: {inserted} comments stored")
            except Exception as e:
                logger.warning(f"  Post {p['id']} comment fetch failed: {e}")
                errors.append(f"{p['id']}: {e}")

        self.repo.log_pipeline_run("comment_fetch", len(posts), total_comments, errors)
        result = {"posts_processed": len(posts), "comments_fetched": total_comments, "errors": errors}
        logger.info(f"Comment fetch complete: {result}")
        return result

    def _flatten_comments(self, comments: list[dict], depth: int = 0) -> list[dict]:
        """Recursively flatten nested comment tree into flat list."""
        flat = []
        for c in comments:
            flat.append({
                "id": c.get("id", ""),
                "parent_id": c.get("parent_id", ""),
                "author": c.get("author", "[deleted]"),
                "body": c.get("body", ""),
                "score": c.get("score", 0),
                "created_utc": c.get("created_utc", 0),
                "depth": depth,
                "is_submitter": c.get("is_submitter", False),
            })
            replies = c.get("replies", [])
            if replies:
                flat.extend(self._flatten_comments(replies, depth + 1))
        return flat

    # ------------------------------------------------------------------
    # Stage: YouTube Comments
    # ------------------------------------------------------------------

    def run_stage_yt_comments(self) -> dict:
        """Fetch comments for YouTube videos that passed AI filter."""
        if not self.yt_collector or not self.yt_repo:
            logger.warning("YouTube not configured, skipping yt_comments")
            return {"error": "not_configured"}

        videos = self.yt_repo.get_videos_needing_comments()
        if not videos:
            logger.info("No YouTube videos need comment fetching")
            return {"videos_processed": 0, "comments_fetched": 0}

        logger.info(f"Fetching comments for {len(videos)} YouTube videos ...")
        total_comments = 0
        errors = []

        for v in videos:
            try:
                comments = self.yt_collector.get_video_comments(v["id"], max_results=100)
                inserted = self.yt_repo.insert_comments(v["id"], comments)
                total_comments += inserted
                logger.debug(f"  Video {v['id']}: {inserted} comments stored")
            except Exception as e:
                logger.warning(f"  Video {v['id']} comment fetch failed: {e}")
                errors.append(f"{v['id']}: {e}")

        self.yt_repo.log_pipeline_run("yt_comments", len(videos), total_comments, errors)
        result = {"videos_processed": len(videos), "comments_fetched": total_comments, "errors": errors}
        logger.info(f"YouTube comment fetch complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Stage 4: KOL Discovery
    # ------------------------------------------------------------------

    def run_stage_kol(self) -> dict:
        """Fetch user profiles for high-value post/comment authors."""
        usernames = self.repo.get_authors_to_fetch(min_score=5, min_comments=10)
        fetched = 0
        errors = []

        if usernames:
            logger.info(f"Fetching profiles for {len(usernames)} authors ...")
            for username in usernames:
                try:
                    profile = self.collector.fetch_user_profile(username)
                    if not profile:
                        logger.debug(f"  {username}: profile not available")
                        continue

                    # Calculate KOL score
                    kol_score, kol_tier = self._calculate_kol_score(profile)
                    profile["kol_score"] = kol_score
                    profile["kol_tier"] = kol_tier

                    self.repo.upsert_author(profile)
                    self.repo.update_author_post_stats(username)
                    fetched += 1
                    logger.debug(f"  {username}: karma={profile['total_karma']}, "
                               f"kol={kol_score:.1f} ({kol_tier})")

                except Exception as e:
                    logger.warning(f"  {username} fetch failed: {e}")
                    errors.append(f"{username}: {e}")
        else:
            logger.info("No new authors to fetch")

        self.repo.log_pipeline_run("kol_fetch", len(usernames), fetched, errors)

        # Sync high-potential KOLs to Notion
        notion_synced = 0
        if self.notion_client:
            kol_to_sync = self.repo.get_kol_authors(min_tier="active")
            if kol_to_sync:
                logger.info(f"Syncing {len(kol_to_sync)} KOLs (active+) to Notion ...")
                for author in kol_to_sync:
                    try:
                        posts = self.repo.get_author_posts(author["username"])
                        page_id = self.notion_client.sync_kol_from_dict(author, posts)
                        if page_id:
                            notion_synced += 1
                    except Exception as e:
                        logger.warning(f"  KOL Notion sync failed for {author['username']}: {e}")

        # --- YouTube KOL: score monitored channels and sync ---
        yt_kol_synced = 0
        if self.yt_repo and self.notion_client:
            channels = self.yt_repo.get_monitored_channels()
            if channels:
                logger.info(f"Scoring {len(channels)} YouTube channels for KOL ...")
                for ch in channels:
                    yt_score, yt_tier = self._calculate_youtube_kol_score(ch)
                    self.yt_repo.update_channel_kol(ch["id"], yt_score, yt_tier)

                    # Sync to Notion KOL DB
                    try:
                        ch_videos = self.yt_repo.get_channel_videos(ch["id"])
                        ch["kol_score"] = yt_score
                        ch["kol_tier"] = yt_tier
                        page_id = self.notion_client.sync_youtube_kol_from_dict(ch, ch_videos)
                        if page_id:
                            self.yt_repo.update_channel_notion_page(ch["id"], page_id)
                            yt_kol_synced += 1
                    except Exception as e:
                        logger.warning(f"  YouTube KOL sync failed for {ch.get('title', '')}: {e}")

        # Summary
        all_authors = self.repo.get_kol_authors(min_tier="watch")
        tier_counts = {}
        for a in all_authors:
            t = a.get("kol_tier", "watch")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        result = {
            "fetched": fetched,
            "notion_synced": notion_synced,
            "yt_kol_synced": yt_kol_synced,
            "total_authors": len(all_authors),
            "tiers": tier_counts,
            "errors": errors,
        }
        logger.info(f"KOL discovery complete: {result}")
        return result

    def _calculate_kol_score(self, profile: dict) -> tuple[float, str]:
        """Calculate KOL score (0-100) and tier from user profile.

        Scoring:
          Karma       0-30  (1 pt per 1000 total_karma, max 30)
          Age         0-10  (2 pts per year, max 10)
          Comment ratio 0-15 (high comment_karma ratio = engaged commenter)
          Verified    0-5   (verified email + gold)
          Activity    0-20  (based on local post count, updated later)
          Engagement  0-20  (based on avg post score in our DB, updated later)
        """
        karma = profile.get("total_karma", 0)
        comment_karma = profile.get("comment_karma", 0)
        age_days = profile.get("account_age_days", 0)

        # Karma score (0-30)
        karma_score = min(karma / 1000, 30)

        # Age score (0-10)
        age_years = age_days / 365
        age_score = min(age_years * 2, 10)

        # Comment engagement ratio (0-15)
        if karma > 0:
            comment_ratio = comment_karma / karma
            comment_score = min(comment_ratio * 15, 15)
        else:
            comment_score = 0

        # Verified bonus (0-5)
        verified_score = 0
        if profile.get("has_verified_email"):
            verified_score += 3
        if profile.get("is_gold"):
            verified_score += 2

        total = karma_score + age_score + comment_score + verified_score

        # Tier assignment
        if total >= 40:
            tier = "expert"
        elif total >= 25:
            tier = "insider"
        elif total >= 15:
            tier = "active"
        else:
            tier = "watch"

        return round(total, 2), tier

    def _calculate_youtube_kol_score(self, channel: dict) -> tuple[float, str]:
        """Calculate KOL score for a YouTube channel.

        Scoring (0-100):
          Subscribers   0-30 (1 pt per 10k subs, max 30)
          Video count   0-10 (1 pt per 50 videos, max 10)
          Total views   0-20 (1 pt per 1M views, max 20)
          Engagement    0-20 (based on local video avg views)
          Monitored     0-20 (bonus for being monitored)
        """
        subs = channel.get("subscriber_count", 0)
        videos = channel.get("video_count", 0)
        views = channel.get("view_count", 0)

        sub_score = min(subs / 10000, 30)
        video_score = min(videos / 50, 10)
        view_score = min(views / 1_000_000, 20)

        # Engagement from local videos
        engagement_score = 0
        if self.yt_repo:
            local_videos = self.yt_repo.get_channel_videos(channel["id"])
            if local_videos:
                avg_views = sum(v.get("view_count", 0) for v in local_videos) / len(local_videos)
                engagement_score = min(avg_views / 5000, 20)

        monitored_bonus = 20 if channel.get("is_monitored") else 0

        total = sub_score + video_score + view_score + engagement_score + monitored_bonus

        if total >= 60:
            tier = "expert"
        elif total >= 40:
            tier = "insider"
        elif total >= 20:
            tier = "active"
        else:
            tier = "watch"

        return round(total, 2), tier

    # ------------------------------------------------------------------
    # Stage 5: Notion Sync
    # ------------------------------------------------------------------

    def run_stage_notion_sync(self) -> dict:
        """Sync filtered posts/videos to Notion + update hot posts/videos."""
        if not self.notion_client:
            logger.warning("Notion client not configured, skipping sync")
            return {"synced": 0, "hot_updated": 0, "error": "no_notion_client"}

        # --- Part 1: Sync new posts ---
        posts = self.repo.get_posts_for_notion_sync()
        synced = 0
        errors = []

        if posts:
            logger.info(f"Syncing {len(posts)} new posts to Notion ...")
            for p in posts:
                try:
                    full_post = self.repo.get_post_with_comments(p["id"])
                    if not full_post:
                        continue

                    page_id = self.notion_client.sync_post_from_dict(full_post)
                    if page_id:
                        self.repo.mark_notion_synced(p["id"], page_id)
                        synced += 1
                        logger.debug(f"  Synced {p['id']} → {page_id}")
                except Exception as e:
                    logger.warning(f"  Notion sync failed for {p['id']}: {e}")
                    errors.append(f"{p['id']}: {e}")
        else:
            logger.info("No new posts to sync to Notion")

        # --- Part 2: Update hot posts (reset 处理状态 to 未处理) ---
        hot_posts = self.repo.get_hot_posts_for_notion_update()
        hot_updated = 0

        if hot_posts:
            logger.info(f"Updating {len(hot_posts)} hot posts in Notion ...")
            for p in hot_posts:
                try:
                    if self.notion_client.update_hot_post(p):
                        self.repo.clear_hot_post_flag(p["id"])
                        hot_updated += 1
                except Exception as e:
                    logger.warning(f"  Hot post update failed for {p['id']}: {e}")
                    errors.append(f"hot:{p['id']}: {e}")
        else:
            logger.info("No hot posts to update in Notion")

        # --- Part 3: Sync YouTube videos ---
        yt_synced = 0
        if self.yt_repo and self.notion_client:
            yt_videos = self.yt_repo.get_videos_for_notion_sync()
            if yt_videos:
                logger.info(f"Syncing {len(yt_videos)} YouTube videos to Notion ...")
                for v in yt_videos:
                    try:
                        full_video = self.yt_repo.get_video_with_comments(v["id"])
                        if not full_video:
                            continue
                        page_id = self.notion_client.sync_youtube_video_from_dict(full_video)
                        if page_id:
                            self.yt_repo.mark_notion_synced(v["id"], page_id)
                            yt_synced += 1
                    except Exception as e:
                        logger.warning(f"  YouTube Notion sync failed for {v['id']}: {e}")
                        errors.append(f"yt:{v['id']}: {e}")
            else:
                logger.info("No new YouTube videos to sync to Notion")

        # --- Part 4: Update hot YouTube videos ---
        yt_hot_updated = 0
        if self.yt_repo and self.notion_client:
            hot_videos = self.yt_repo.get_hot_videos_for_notion_update()
            if hot_videos:
                logger.info(f"Updating {len(hot_videos)} hot YouTube videos in Notion ...")
                for v in hot_videos:
                    try:
                        if self.notion_client.update_hot_youtube_video(v):
                            self.yt_repo.clear_hot_video_flag(v["id"])
                            yt_hot_updated += 1
                    except Exception as e:
                        logger.warning(f"  Hot video update failed for {v['id']}: {e}")
                        errors.append(f"yt_hot:{v['id']}: {e}")

        self.repo.log_pipeline_run("notion_sync", len(posts) + len(hot_posts), synced + hot_updated, errors)
        result = {
            "synced": synced,
            "total_new": len(posts),
            "hot_updated": hot_updated,
            "total_hot": len(hot_posts),
            "yt_synced": yt_synced,
            "yt_hot_updated": yt_hot_updated,
            "errors": errors,
        }
        logger.info(f"Notion sync complete: {result}")
        return result
