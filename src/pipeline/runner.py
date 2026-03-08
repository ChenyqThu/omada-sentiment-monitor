"""4-stage pipeline orchestrator: scrape → AI filter → comment fetch → Notion sync."""
import logging
from datetime import datetime, timezone

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
    ):
        self.repo = repo
        self.collector = collector
        self.ai_filter = ai_filter
        self.notion_client = notion_client
        self.subreddits = subreddits or []
        self.max_per_sub = max_per_sub
        self.relevance_threshold = relevance_threshold

    def run(self, stages: list[str] = None) -> dict:
        """Execute pipeline stages. Default: all stages in order.

        Args:
            stages: list of stage names to run. Options:
                    ['scrape', 'ai_filter', 'comments', 'kol', 'notion_sync']
                    If None, runs all stages.
        Returns:
            Summary dict with stats for each stage.
        """
        all_stages = ["scrape", "ai_filter", "comments", "kol", "notion_sync"]
        stages = stages or all_stages
        summary = {}

        for stage in stages:
            if stage not in all_stages:
                logger.warning(f"Unknown stage: {stage}, skipping")
                continue

            logger.info(f"{'='*60}")
            logger.info(f"STAGE: {stage}")
            logger.info(f"{'='*60}")

            try:
                if stage == "scrape":
                    summary["scrape"] = self.run_stage_scrape()
                elif stage == "ai_filter":
                    summary["ai_filter"] = self.run_stage_ai_filter()
                elif stage == "comments":
                    summary["comments"] = self.run_stage_comments()
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
        """Fetch all new posts from target subreddits into SQLite."""
        total_new = 0
        total_updated = 0
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

                # Update stats for existing posts
                for p in posts:
                    if new_count == 0 or True:  # always try update
                        self.repo.update_post_stats(
                            p["id"], p.get("score", 0), p.get("num_comments", 0)
                        )
                        total_updated += 1

                logger.info(f"  r/{sub}: {len(posts)} fetched, {new_count} new")

            except Exception as e:
                logger.error(f"  r/{sub} scrape failed: {e}")
                errors.append(f"r/{sub}: {e}")

        self.repo.log_pipeline_run("scrape", total_new + total_updated, total_new, errors)
        result = {"new_posts": total_new, "updated": total_updated, "errors": errors}
        logger.info(f"Scrape complete: {result}")
        return result

    # ------------------------------------------------------------------
    # Stage 2: AI Filter
    # ------------------------------------------------------------------

    def run_stage_ai_filter(self) -> dict:
        """Run AI batch filter on all scraped (unprocessed) posts."""
        if not self.ai_filter:
            logger.warning("AI filter not configured (missing API key), skipping")
            return {"processed": 0, "filtered": 0, "rejected": 0, "skipped": "no_api_key"}

        posts = self.repo.get_posts_by_status("scraped")
        if not posts:
            logger.info("No unprocessed posts to filter")
            return {"processed": 0, "filtered": 0, "rejected": 0}

        logger.info(f"AI filtering {len(posts)} posts ...")
        results = self.ai_filter.filter_all(posts)

        filtered, rejected = self.repo.update_ai_filter_results(
            results, threshold=self.relevance_threshold
        )

        self.repo.log_pipeline_run(
            "ai_filter", len(posts), filtered,
            model=self.ai_filter.provider.model_name,
        )

        result = {"processed": len(posts), "filtered": filtered, "rejected": rejected}
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

        # Summary
        all_authors = self.repo.get_kol_authors(min_tier="watch")
        tier_counts = {}
        for a in all_authors:
            t = a.get("kol_tier", "watch")
            tier_counts[t] = tier_counts.get(t, 0) + 1

        result = {
            "fetched": fetched,
            "notion_synced": notion_synced,
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

    # ------------------------------------------------------------------
    # Stage 5: Notion Sync
    # ------------------------------------------------------------------

    def run_stage_notion_sync(self) -> dict:
        """Sync filtered posts to Notion."""
        if not self.notion_client:
            logger.warning("Notion client not configured, skipping sync")
            return {"synced": 0, "error": "no_notion_client"}

        posts = self.repo.get_posts_for_notion_sync()
        if not posts:
            logger.info("No posts to sync to Notion")
            return {"synced": 0}

        logger.info(f"Syncing {len(posts)} posts to Notion ...")
        synced = 0
        errors = []

        for p in posts:
            try:
                # Get post with comments for full content
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

        self.repo.log_pipeline_run("notion_sync", len(posts), synced, errors)
        result = {"synced": synced, "total": len(posts), "errors": errors}
        logger.info(f"Notion sync complete: {result}")
        return result
