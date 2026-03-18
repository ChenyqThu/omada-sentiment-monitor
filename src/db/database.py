"""SQLite database connection manager and schema initialization."""
import os
import sqlite3
import logging

logger = logging.getLogger(__name__)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS posts (
    id              TEXT PRIMARY KEY,
    subreddit       TEXT NOT NULL,
    title           TEXT NOT NULL,
    selftext        TEXT DEFAULT '',
    author          TEXT DEFAULT '[deleted]',
    score           INTEGER DEFAULT 0,
    upvote_ratio    REAL DEFAULT 0.0,
    num_comments    INTEGER DEFAULT 0,
    created_utc     REAL NOT NULL,
    permalink       TEXT NOT NULL,
    url             TEXT DEFAULT '',
    link_flair_text TEXT,
    is_self         INTEGER DEFAULT 1,

    -- Pipeline status
    status          TEXT NOT NULL DEFAULT 'scraped'
                    CHECK(status IN ('scraped','ai_filtered','notion_synced','rejected')),
    scraped_at      TEXT NOT NULL,
    filtered_at     TEXT,
    synced_at       TEXT,

    -- AI filter results
    ai_relevance_score      REAL,
    ai_topic_category       TEXT,
    ai_sentiment_quick      TEXT,
    ai_should_collect_comments INTEGER,
    ai_brief_reason         TEXT,
    ai_filter_model         TEXT,

    -- Notion sync tracking
    notion_page_id          TEXT,
    notion_last_updated     TEXT,

    -- Hot post detection
    prev_score              INTEGER,
    prev_num_comments       INTEGER,
    is_hot_post             INTEGER DEFAULT 0,
    hot_post_detected_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_posts_status ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON posts(subreddit, created_utc);
CREATE INDEX IF NOT EXISTS idx_posts_created ON posts(created_utc);

CREATE TABLE IF NOT EXISTS comments (
    id              TEXT PRIMARY KEY,
    post_id         TEXT NOT NULL REFERENCES posts(id),
    parent_id       TEXT,
    author          TEXT DEFAULT '[deleted]',
    body            TEXT DEFAULT '',
    score           INTEGER DEFAULT 0,
    created_utc     REAL NOT NULL,
    depth           INTEGER DEFAULT 0,
    is_submitter    INTEGER DEFAULT 0,
    fetched_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_comments_post ON comments(post_id);

CREATE TABLE IF NOT EXISTS authors (
    username        TEXT PRIMARY KEY,
    total_karma     INTEGER DEFAULT 0,
    link_karma      INTEGER DEFAULT 0,
    comment_karma   INTEGER DEFAULT 0,
    created_utc     REAL DEFAULT 0,
    is_gold         INTEGER DEFAULT 0,
    is_mod          INTEGER DEFAULT 0,
    has_verified_email INTEGER DEFAULT 0,
    account_age_days INTEGER DEFAULT 0,

    -- Computed KOL metrics
    kol_score       REAL DEFAULT 0,
    kol_tier        TEXT DEFAULT 'watch'
                    CHECK(kol_tier IN ('expert','insider','active','watch')),
    post_count      INTEGER DEFAULT 0,
    avg_post_score  REAL DEFAULT 0,
    first_seen_at   TEXT,
    last_seen_at    TEXT,
    fetched_at      TEXT,

    -- Notion sync
    notion_page_id  TEXT
);

CREATE INDEX IF NOT EXISTS idx_authors_kol ON authors(kol_score DESC);
CREATE INDEX IF NOT EXISTS idx_authors_tier ON authors(kol_tier);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,
    finished_at     TEXT,
    stage           TEXT NOT NULL
                    CHECK(stage IN ('scrape','ai_filter','comment_fetch','kol_fetch','notion_sync')),
    posts_processed INTEGER DEFAULT 0,
    posts_passed    INTEGER DEFAULT 0,
    errors          TEXT,
    model_used      TEXT
);
"""


class Database:
    """SQLite connection manager with schema auto-initialization."""

    def __init__(self, db_path: str = "data/omada_monitor.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._init_schema()
        return self._conn

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self._migrate()
        logger.info(f"Database initialized: {self.db_path}")

    def _migrate(self):
        """Add columns that may be missing from older databases."""
        cursor = self._conn.execute("PRAGMA table_info(posts)")
        existing = {row[1] for row in cursor.fetchall()}

        migrations = [
            ("prev_score", "INTEGER"),
            ("prev_num_comments", "INTEGER"),
            ("is_hot_post", "INTEGER DEFAULT 0"),
            ("hot_post_detected_at", "TEXT"),
        ]
        for col_name, col_type in migrations:
            if col_name not in existing:
                self._conn.execute(f"ALTER TABLE posts ADD COLUMN {col_name} {col_type}")
                logger.info(f"Migrated: added column posts.{col_name}")
        self._conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
