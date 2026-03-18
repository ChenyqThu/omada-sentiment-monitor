"""CRUD operations for the local SQLite database."""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from .database import Database

logger = logging.getLogger(__name__)


class PostRepository:
    """All database read/write operations for the pipeline."""

    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Posts — insert / update
    # ------------------------------------------------------------------

    def insert_posts(self, posts: list[dict]) -> int:
        """INSERT OR IGNORE scraped posts. Returns count of newly inserted rows."""
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for p in posts:
            try:
                self.db.conn.execute(
                    """INSERT OR IGNORE INTO posts
                       (id, subreddit, title, selftext, author, score, upvote_ratio,
                        num_comments, created_utc, permalink, url, link_flair_text,
                        is_self, status, scraped_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'scraped',?)""",
                    (
                        p["id"], p.get("subreddit", ""), p.get("title", ""),
                        p.get("selftext", ""), p.get("author", "[deleted]"),
                        p.get("score", 0), p.get("upvote_ratio", 0.0),
                        p.get("num_comments", 0), p.get("created_utc", 0),
                        p.get("permalink", ""), p.get("url", ""),
                        p.get("link_flair_text"), 1 if p.get("is_self", True) else 0,
                        now,
                    ),
                )
                if self.db.conn.total_changes:
                    inserted += 1
            except Exception as e:
                logger.warning(f"Insert post {p.get('id')} failed: {e}")
        self.db.conn.commit()
        return inserted

    def update_post_stats(self, post_id: str, score: int, num_comments: int) -> bool:
        """Update score/num_comments for already-seen posts.

        Saves previous values for hot post detection.
        Returns True if this post qualifies as a hot post (significant change).
        """
        row = self.db.conn.execute(
            "SELECT score, num_comments FROM posts WHERE id=?", (post_id,)
        ).fetchone()
        if not row:
            return False

        old_score = row["score"] or 0
        old_comments = row["num_comments"] or 0

        is_hot = self._is_hot_post_change(old_score, score, old_comments, num_comments)

        now = datetime.now(timezone.utc).isoformat()
        if is_hot:
            self.db.conn.execute(
                """UPDATE posts SET
                     prev_score=?, prev_num_comments=?,
                     score=?, num_comments=?,
                     is_hot_post=1, hot_post_detected_at=?
                   WHERE id=?""",
                (old_score, old_comments, score, num_comments, now, post_id),
            )
        else:
            self.db.conn.execute(
                """UPDATE posts SET
                     prev_score=?, prev_num_comments=?,
                     score=?, num_comments=?
                   WHERE id=?""",
                (old_score, old_comments, score, num_comments, post_id),
            )
        self.db.conn.commit()
        return is_hot

    @staticmethod
    def _is_hot_post_change(
        old_score: int, new_score: int,
        old_comments: int, new_comments: int,
    ) -> bool:
        """Determine if a post has become a hot post based on score/comment changes.

        Criteria (any one triggers):
        - Score increase >= 50% AND absolute increase >= 10
        - Comment increase >= 50% AND absolute increase >= 5
        - Absolute score jump >= 50
        - Absolute comment jump >= 20
        """
        score_diff = new_score - old_score
        comment_diff = new_comments - old_comments

        if score_diff >= 50 or comment_diff >= 20:
            return True

        if old_score > 0 and score_diff >= 10 and score_diff / old_score >= 0.5:
            return True

        if old_comments > 0 and comment_diff >= 5 and comment_diff / old_comments >= 0.5:
            return True

        return False

    def get_hot_posts_for_notion_update(self) -> list[dict]:
        """Get hot posts that already have Notion pages and need updating."""
        rows = self.db.conn.execute(
            """SELECT * FROM posts
               WHERE is_hot_post = 1
                 AND notion_page_id IS NOT NULL
               ORDER BY hot_post_detected_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_hot_post_flag(self, post_id: str) -> None:
        """Clear hot post flag after Notion update."""
        self.db.conn.execute(
            "UPDATE posts SET is_hot_post=0 WHERE id=?", (post_id,)
        )
        self.db.conn.commit()

    # ------------------------------------------------------------------
    # Posts — query by status
    # ------------------------------------------------------------------

    def get_posts_by_status(self, status: str, limit: int = 500) -> list[dict]:
        """Get posts with given status, ordered by created_utc DESC."""
        rows = self.db.conn.execute(
            "SELECT * FROM posts WHERE status=? ORDER BY created_utc DESC LIMIT ?",
            (status, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_unprocessed_count(self) -> dict:
        """Get counts of posts by status."""
        rows = self.db.conn.execute(
            "SELECT status, COUNT(*) as cnt FROM posts GROUP BY status"
        ).fetchall()
        return {r["status"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # AI filter results
    # ------------------------------------------------------------------

    def update_ai_filter_results(self, results: list[dict], threshold: float = 0.4) -> tuple[int, int]:
        """Batch update AI filter results. Returns (filtered_count, rejected_count)."""
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
                """UPDATE posts SET
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

    def get_posts_needing_comments(self) -> list[dict]:
        """Posts that passed AI filter and need comment fetching."""
        rows = self.db.conn.execute(
            """SELECT p.* FROM posts p
               WHERE p.status='ai_filtered'
                 AND p.ai_should_collect_comments=1
                 AND p.id NOT IN (SELECT DISTINCT post_id FROM comments)
               ORDER BY p.created_utc DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def insert_comments(self, post_id: str, comments: list[dict]) -> int:
        """Bulk insert comments for a post. Returns count inserted."""
        now = datetime.now(timezone.utc).isoformat()
        inserted = 0
        for c in comments:
            try:
                self.db.conn.execute(
                    """INSERT OR IGNORE INTO comments
                       (id, post_id, parent_id, author, body, score,
                        created_utc, depth, is_submitter, fetched_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""",
                    (
                        c["id"], post_id, c.get("parent_id", ""),
                        c.get("author", "[deleted]"), c.get("body", ""),
                        c.get("score", 0), c.get("created_utc", 0),
                        c.get("depth", 0),
                        1 if c.get("is_submitter") else 0,
                        now,
                    ),
                )
                inserted += 1
            except Exception as e:
                logger.debug(f"Insert comment {c.get('id')} failed: {e}")
        self.db.conn.commit()
        return inserted

    def get_comments_for_post(self, post_id: str) -> list[dict]:
        """Get all comments for a post, ordered by depth then score."""
        rows = self.db.conn.execute(
            """SELECT * FROM comments
               WHERE post_id=?
               ORDER BY depth ASC, score DESC""",
            (post_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_post_with_comments(self, post_id: str) -> Optional[dict]:
        """Return post dict with nested comments list."""
        row = self.db.conn.execute(
            "SELECT * FROM posts WHERE id=?", (post_id,)
        ).fetchone()
        if not row:
            return None
        post = dict(row)
        post["comments"] = self.get_comments_for_post(post_id)
        return post

    # ------------------------------------------------------------------
    # Notion sync
    # ------------------------------------------------------------------

    def get_posts_for_notion_sync(self) -> list[dict]:
        """Posts that passed AI filter but haven't been synced to Notion."""
        rows = self.db.conn.execute(
            """SELECT * FROM posts
               WHERE status='ai_filtered'
               ORDER BY created_utc DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_notion_synced(self, post_id: str, notion_page_id: str) -> None:
        """Mark a post as synced to Notion."""
        now = datetime.now(timezone.utc).isoformat()
        self.db.conn.execute(
            """UPDATE posts SET status='notion_synced',
                 notion_page_id=?, notion_last_updated=?, synced_at=?
               WHERE id=?""",
            (notion_page_id, now, now, post_id),
        )
        self.db.conn.commit()

    # ------------------------------------------------------------------
    # Authors / KOL
    # ------------------------------------------------------------------

    def get_authors_to_fetch(self, min_score: int = 5, min_comments: int = 10) -> list[str]:
        """Get author usernames from high-value posts/comments that haven't been fetched yet.
        Returns unique usernames not already in the authors table.
        """
        # Authors from high-value posts (any non-rejected status)
        post_authors = self.db.conn.execute(
            """SELECT DISTINCT p.author FROM posts p
               WHERE p.status != 'rejected'
                 AND p.author != '[deleted]'
                 AND (p.score >= ? OR p.num_comments >= ?)
                 AND p.author NOT IN (SELECT username FROM authors)""",
            (min_score, min_comments),
        ).fetchall()

        # Authors from high-score comments
        comment_authors = self.db.conn.execute(
            """SELECT DISTINCT c.author FROM comments c
               WHERE c.author != '[deleted]'
                 AND c.score >= ?
                 AND c.author NOT IN (SELECT username FROM authors)""",
            (min_score,),
        ).fetchall()

        usernames = set()
        for r in post_authors:
            usernames.add(r["author"])
        for r in comment_authors:
            usernames.add(r["author"])
        return list(usernames)

    def upsert_author(self, author: dict) -> None:
        """Insert or update an author record."""
        now = datetime.now(timezone.utc).isoformat()
        self.db.conn.execute(
            """INSERT INTO authors
               (username, total_karma, link_karma, comment_karma, created_utc,
                is_gold, is_mod, has_verified_email, account_age_days,
                kol_score, kol_tier, first_seen_at, last_seen_at, fetched_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(username) DO UPDATE SET
                 total_karma=excluded.total_karma,
                 link_karma=excluded.link_karma,
                 comment_karma=excluded.comment_karma,
                 is_gold=excluded.is_gold,
                 is_mod=excluded.is_mod,
                 kol_score=excluded.kol_score,
                 kol_tier=excluded.kol_tier,
                 last_seen_at=excluded.last_seen_at,
                 fetched_at=excluded.fetched_at""",
            (
                author["username"],
                author.get("total_karma", 0),
                author.get("link_karma", 0),
                author.get("comment_karma", 0),
                author.get("created_utc", 0),
                1 if author.get("is_gold") else 0,
                1 if author.get("is_mod") else 0,
                1 if author.get("has_verified_email") else 0,
                author.get("account_age_days", 0),
                author.get("kol_score", 0),
                author.get("kol_tier", "watch"),
                now, now, now,
            ),
        )
        self.db.conn.commit()

    def update_author_post_stats(self, username: str) -> None:
        """Recompute post_count and avg_post_score from local posts table."""
        row = self.db.conn.execute(
            """SELECT COUNT(*) as cnt, COALESCE(AVG(score), 0) as avg_score
               FROM posts WHERE author=? AND status != 'rejected'""",
            (username,),
        ).fetchone()
        if row:
            self.db.conn.execute(
                "UPDATE authors SET post_count=?, avg_post_score=? WHERE username=?",
                (row["cnt"], round(row["avg_score"], 2), username),
            )
            self.db.conn.commit()

    def get_kol_authors(self, min_tier: str = "active") -> list[dict]:
        """Get authors at or above a KOL tier."""
        tier_order = {"expert": 4, "insider": 3, "active": 2, "watch": 1}
        min_val = tier_order.get(min_tier, 1)
        all_rows = self.db.conn.execute(
            "SELECT * FROM authors ORDER BY kol_score DESC"
        ).fetchall()
        results = []
        for r in all_rows:
            if tier_order.get(r["kol_tier"], 0) >= min_val:
                results.append(dict(r))
        return results

    def get_author_posts(self, username: str) -> list[dict]:
        """Get all posts by an author."""
        rows = self.db.conn.execute(
            "SELECT * FROM posts WHERE author=? ORDER BY created_utc DESC",
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]

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
