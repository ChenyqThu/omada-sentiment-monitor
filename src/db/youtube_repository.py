"""CRUD operations for YouTube data in the local SQLite database."""
import json
import logging
from datetime import datetime, timezone, date

from .database import Database

logger = logging.getLogger(__name__)


class YouTubeRepository:
    """Database read/write operations for YouTube pipeline data."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Videos — insert / update
    # ------------------------------------------------------------------

    def insert_videos(self, videos: list[dict]) -> int:
        """INSERT OR IGNORE scraped videos. Returns count of newly inserted rows."""
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for v in videos:
            try:
                self.db.conn.execute(
                    """INSERT OR IGNORE INTO youtube_videos
                       (id, channel_id, channel_title, title, description,
                        published_at, url, thumbnail_url, duration, tags, category_id,
                        view_count, like_count, comment_count,
                        status, scraped_at, discovered_via)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'scraped',?,?)""",
                    (
                        v["id"],
                        v.get("channel_id", ""),
                        v.get("channel_title", ""),
                        v.get("title", ""),
                        v.get("description", ""),
                        v.get("published_at", ""),
                        v.get("url", f"https://www.youtube.com/watch?v={v['id']}"),
                        v.get("thumbnail_url", ""),
                        v.get("duration", ""),
                        json.dumps(v.get("tags", []), ensure_ascii=False),
                        v.get("category_id", ""),
                        v.get("view_count", 0),
                        v.get("like_count", 0),
                        v.get("comment_count", 0),
                        now,
                        v.get("discovered_via", "search"),
                    ),
                )
                if self.db.conn.total_changes:
                    inserted += 1
            except Exception as e:
                logger.warning(f"Insert video {v.get('id')} failed: {e}")
        self.db.conn.commit()
        return inserted

    def update_video_stats(
        self, video_id: str, view_count: int, like_count: int, comment_count: int,
        hot_view_jump: int = 5000, hot_like_jump: int = 200, hot_comment_jump: int = 50,
    ) -> bool:
        """Update stats for an already-seen video. Returns True if hot video detected."""
        row = self.db.conn.execute(
            "SELECT view_count, like_count, comment_count FROM youtube_videos WHERE id=?",
            (video_id,),
        ).fetchone()
        if not row:
            return False

        old_views = row["view_count"] or 0
        old_likes = row["like_count"] or 0
        old_comments = row["comment_count"] or 0

        is_hot = self._is_hot_video_change(
            old_views, view_count, old_likes, like_count,
            old_comments, comment_count,
            hot_view_jump, hot_like_jump, hot_comment_jump,
        )

        now = datetime.now(timezone.utc).isoformat()
        if is_hot:
            self.db.conn.execute(
                """UPDATE youtube_videos SET
                     prev_view_count=?, prev_like_count=?, prev_comment_count=?,
                     view_count=?, like_count=?, comment_count=?,
                     is_hot_video=1, hot_video_detected_at=?
                   WHERE id=?""",
                (old_views, old_likes, old_comments,
                 view_count, like_count, comment_count, now, video_id),
            )
        else:
            self.db.conn.execute(
                """UPDATE youtube_videos SET
                     prev_view_count=?, prev_like_count=?, prev_comment_count=?,
                     view_count=?, like_count=?, comment_count=?
                   WHERE id=?""",
                (old_views, old_likes, old_comments,
                 view_count, like_count, comment_count, video_id),
            )
        self.db.conn.commit()
        return is_hot

    @staticmethod
    def _is_hot_video_change(
        old_views: int, new_views: int,
        old_likes: int, new_likes: int,
        old_comments: int, new_comments: int,
        hot_view_jump: int = 5000,
        hot_like_jump: int = 200,
        hot_comment_jump: int = 50,
    ) -> bool:
        """Determine if a video has become hot based on stat changes."""
        view_diff = new_views - old_views
        like_diff = new_likes - old_likes
        comment_diff = new_comments - old_comments

        # Absolute jumps
        if view_diff >= hot_view_jump:
            return True
        if like_diff >= hot_like_jump:
            return True
        if comment_diff >= hot_comment_jump:
            return True

        # Percentage growth >= 50% with minimum thresholds
        if old_views > 0 and view_diff >= 500 and view_diff / old_views >= 0.5:
            return True
        if old_likes > 0 and like_diff >= 20 and like_diff / old_likes >= 0.5:
            return True
        if old_comments > 0 and comment_diff >= 10 and comment_diff / old_comments >= 0.5:
            return True

        return False

    def get_hot_videos_for_notion_update(self) -> list[dict]:
        """Get hot videos that already have Notion pages and need updating."""
        rows = self.db.conn.execute(
            """SELECT * FROM youtube_videos
               WHERE is_hot_video = 1
                 AND notion_page_id IS NOT NULL
               ORDER BY hot_video_detected_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_hot_video_flag(self, video_id: str) -> None:
        """Clear hot video flag after Notion update."""
        self.db.conn.execute(
            "UPDATE youtube_videos SET is_hot_video=0 WHERE id=?", (video_id,)
        )
        self.db.conn.commit()

    # ------------------------------------------------------------------
    # Videos — query by status
    # ------------------------------------------------------------------

    def get_videos_by_status(self, status: str, limit: int = 500) -> list[dict]:
        """Get videos with given status, ordered by published_at DESC."""
        rows = self.db.conn.execute(
            "SELECT * FROM youtube_videos WHERE status=? ORDER BY published_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unprocessed_count(self) -> dict:
        """Get counts of videos by status."""
        rows = self.db.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM youtube_videos GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    def get_recent_video_ids(self, days: int = 7) -> list[str]:
        """Get video IDs published within the last N days."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        rows = self.db.conn.execute(
            "SELECT id FROM youtube_videos WHERE published_at >= ?",
            (cutoff,),
        ).fetchall()
        return [r["id"] for r in rows]

    # ------------------------------------------------------------------
    # AI filter results
    # ------------------------------------------------------------------

    def update_ai_filter_results(self, results: list[dict], threshold: float = 0.4) -> tuple[int, int]:
        """Batch update AI filter results for YouTube videos."""
        filtered = 0
        rejected = 0
        now = datetime.now(timezone.utc).isoformat()
        for r in results:
            score = r.get("relevance_score", 0.0)
            new_status = "ai_filtered" if score >= threshold else "rejected"
            if new_status == "ai_filtered":
                filtered += 1
            else:
                rejected += 1
            self.db.conn.execute(
                """UPDATE youtube_videos SET
                     ai_relevance_score=?, ai_topic_category=?, ai_sentiment_quick=?,
                     ai_should_collect_comments=?, ai_brief_reason=?, ai_filter_model=?,
                     status=?, filtered_at=?
                   WHERE id=? AND status='scraped'""",
                (
                    score,
                    r.get("topic_category", ""),
                    r.get("sentiment_quick", "neutral"),
                    1 if r.get("should_collect_comments") else 0,
                    r.get("brief_reason", ""),
                    r.get("filter_model", ""),
                    new_status, now,
                    r["post_id"],
                ),
            )
        self.db.conn.commit()
        return filtered, rejected

    # ------------------------------------------------------------------
    # Comments
    # ------------------------------------------------------------------

    def get_videos_needing_comments(self) -> list[dict]:
        """Videos that passed AI filter and need comment fetching."""
        rows = self.db.conn.execute(
            """SELECT v.* FROM youtube_videos v
               WHERE v.status='ai_filtered'
                 AND v.ai_should_collect_comments=1
                 AND v.id NOT IN (SELECT DISTINCT video_id FROM youtube_comments)
               ORDER BY v.published_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_comments(self, video_id: str, comments: list[dict]) -> int:
        """Bulk insert comments for a video. Returns count inserted."""
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for c in comments:
            try:
                self.db.conn.execute(
                    """INSERT OR IGNORE INTO youtube_comments
                       (id, video_id, parent_id, author, author_channel_id,
                        text, like_count, published_at, is_reply, fetched_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        c["id"], video_id, c.get("parent_id", ""),
                        c.get("author", ""), c.get("author_channel_id", ""),
                        c.get("text", ""), c.get("like_count", 0),
                        c.get("published_at", ""),
                        1 if c.get("is_reply") else 0,
                        now,
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.debug(f"Insert YouTube comment {c.get('id')} failed: {e}")
        self.db.conn.commit()
        return inserted

    def get_comments_for_video(self, video_id: str) -> list[dict]:
        """Get all comments for a video, ordered by like_count DESC."""
        rows = self.db.conn.execute(
            """SELECT * FROM youtube_comments
               WHERE video_id=?
               ORDER BY is_reply ASC, like_count DESC""",
            (video_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_video_with_comments(self, video_id: str) -> dict | None:
        """Return video dict with nested comments list."""
        row = self.db.conn.execute(
            "SELECT * FROM youtube_videos WHERE id=?", (video_id,)
        ).fetchone()
        if not row:
            return None
        video = dict(row)
        video["comments"] = self.get_comments_for_video(video_id)
        return video

    # ------------------------------------------------------------------
    # Notion sync
    # ------------------------------------------------------------------

    def get_videos_for_notion_sync(self) -> list[dict]:
        """Videos that passed AI filter but haven't been synced to Notion."""
        rows = self.db.conn.execute(
            """SELECT * FROM youtube_videos
               WHERE status='ai_filtered'
               ORDER BY published_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_notion_synced(self, video_id: str, notion_page_id: str) -> None:
        """Mark a video as synced to Notion."""
        now = datetime.now(timezone.utc).isoformat()
        self.db.conn.execute(
            """UPDATE youtube_videos SET status='notion_synced',
                 notion_page_id=?, notion_last_updated=?, synced_at=?
               WHERE id=?""",
            (notion_page_id, now, now, video_id),
        )
        self.db.conn.commit()

    # ------------------------------------------------------------------
    # Channels
    # ------------------------------------------------------------------

    def upsert_channel(self, channel: dict) -> None:
        """Insert or update a YouTube channel record."""
        self.db.conn.execute(
            """INSERT INTO youtube_channels
               (id, title, description, custom_url, thumbnail_url,
                subscriber_count, video_count, view_count,
                uploads_playlist_id, is_monitored, last_checked_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(id) DO UPDATE SET
                 title=excluded.title,
                 description=excluded.description,
                 custom_url=excluded.custom_url,
                 thumbnail_url=excluded.thumbnail_url,
                 subscriber_count=excluded.subscriber_count,
                 video_count=excluded.video_count,
                 view_count=excluded.view_count,
                 uploads_playlist_id=excluded.uploads_playlist_id,
                 last_checked_at=excluded.last_checked_at""",
            (
                channel["id"],
                channel.get("title", ""),
                channel.get("description", ""),
                channel.get("custom_url", ""),
                channel.get("thumbnail_url", ""),
                channel.get("subscriber_count", 0),
                channel.get("video_count", 0),
                channel.get("view_count", 0),
                channel.get("uploads_playlist_id", ""),
                1 if channel.get("is_monitored") else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self.db.conn.commit()

    def get_monitored_channels(self) -> list[dict]:
        """Get all monitored channels with their uploads_playlist_id."""
        rows = self.db.conn.execute(
            """SELECT * FROM youtube_channels
               WHERE is_monitored=1
               ORDER BY monitor_priority DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def update_channel_kol(self, channel_id: str, kol_score: float, kol_tier: str) -> None:
        """Update KOL score for a channel."""
        self.db.conn.execute(
            "UPDATE youtube_channels SET kol_score=?, kol_tier=? WHERE id=?",
            (kol_score, kol_tier, channel_id),
        )
        self.db.conn.commit()

    def update_channel_notion_page(self, channel_id: str, notion_page_id: str) -> None:
        """Update Notion page ID for a channel."""
        self.db.conn.execute(
            "UPDATE youtube_channels SET notion_page_id=? WHERE id=?",
            (notion_page_id, channel_id),
        )
        self.db.conn.commit()

    def get_kol_channels(self, min_tier: str = "active") -> list[dict]:
        """Get channels at or above a KOL tier."""
        tier_order = {"expert": 4, "insider": 3, "active": 2, "watch": 1}
        min_val = tier_order.get(min_tier, 1)
        all_rows = self.db.conn.execute(
            "SELECT * FROM youtube_channels WHERE kol_score > 0 ORDER BY kol_score DESC"
        ).fetchall()
        return [dict(r) for r in all_rows if tier_order.get(r["kol_tier"], 0) >= min_val]

    def get_channel_videos(self, channel_id: str) -> list[dict]:
        """Get all videos for a channel."""
        rows = self.db.conn.execute(
            "SELECT * FROM youtube_videos WHERE channel_id=? ORDER BY published_at DESC",
            (channel_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Quota tracking
    # ------------------------------------------------------------------

    def track_quota(self, units: int, is_search: bool = False) -> None:
        """Track API quota usage for today."""
        today = date.today().isoformat()
        self.db.conn.execute(
            """INSERT INTO youtube_quota (date, units_used, search_units, other_units)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 units_used = units_used + ?,
                 search_units = search_units + ?,
                 other_units = other_units + ?""",
            (
                today, units,
                units if is_search else 0,
                0 if is_search else units,
                units,
                units if is_search else 0,
                0 if is_search else units,
            ),
        )
        self.db.conn.commit()

    def get_daily_quota_used(self) -> int:
        """Get total quota units used today."""
        today = date.today().isoformat()
        row = self.db.conn.execute(
            "SELECT units_used FROM youtube_quota WHERE date=?", (today,)
        ).fetchone()
        return row["units_used"] if row else 0

    def get_quota_details(self) -> dict:
        """Get detailed quota info for today."""
        today = date.today().isoformat()
        row = self.db.conn.execute(
            "SELECT * FROM youtube_quota WHERE date=?", (today,)
        ).fetchone()
        if row:
            return dict(row)
        return {"date": today, "units_used": 0, "search_units": 0, "other_units": 0}

    # ------------------------------------------------------------------
    # Search state
    # ------------------------------------------------------------------

    def get_search_state(self, query_key: str) -> dict | None:
        """Get last search state for a query."""
        row = self.db.conn.execute(
            "SELECT * FROM youtube_search_state WHERE query_key=?", (query_key,)
        ).fetchone()
        return dict(row) if row else None

    def update_search_state(self, query_key: str, result_count: int) -> None:
        """Update search state after a query."""
        now = datetime.now(timezone.utc).isoformat()
        self.db.conn.execute(
            """INSERT INTO youtube_search_state (query_key, last_search_at, last_result_count)
               VALUES (?, ?, ?)
               ON CONFLICT(query_key) DO UPDATE SET
                 last_search_at=excluded.last_search_at,
                 last_result_count=excluded.last_result_count""",
            (query_key, now, result_count),
        )
        self.db.conn.commit()

    # ------------------------------------------------------------------
    # Pipeline run logging
    # ------------------------------------------------------------------

    def log_pipeline_run(
        self, stage: str, processed: int, passed: int,
        errors: list[str] = None, model: str = None,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self.db.conn.execute(
            """INSERT INTO pipeline_runs
               (started_at, finished_at, stage, posts_processed, posts_passed, errors, model_used)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (now, now, stage, processed, passed,
             json.dumps(errors or []), model),
        )
        self.db.conn.commit()
