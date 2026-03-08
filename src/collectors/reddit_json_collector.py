"""
Reddit JSON Collector
Fetches Reddit data using the public .json endpoint via httpx (no PRAW dependency).
"""
import time
import os
import sys
from typing import Optional

import httpx

# Add project root to Python path
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.logger import LoggerMixin

# Default user-agent
_DEFAULT_USER_AGENT = "OmadaPulseMonitor/2.0"

# Reddit base URL
_REDDIT_BASE = "https://www.reddit.com"

# Retry settings
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0  # seconds


class RedditJsonCollector(LoggerMixin):
    """Reddit data collector using the public .json endpoint via httpx."""

    def __init__(self, config: Optional[dict] = None):
        """
        Initialize the collector.

        Args:
            config: Optional dict with keys:
                - user_agent (str): override default user-agent
                - timeout (float): HTTP timeout in seconds (default 30)
        """
        if config is None:
            config = {}

        self._user_agent = config.get("user_agent", _DEFAULT_USER_AGENT)
        self._timeout = config.get("timeout", 30.0)

        # httpx client with persistent headers and redirect following
        self._client = httpx.Client(
            headers={
                "User-Agent": self._user_agent,
                "Accept": "application/json",
            },
            follow_redirects=True,
            timeout=self._timeout,
        )

        # Rate-limiter state (populated from response headers)
        self._rate_limit_remaining: Optional[float] = None
        self._rate_limit_reset: Optional[float] = None  # seconds until window reset

        self.logger.info(
            f"RedditJsonCollector initialised with user-agent: {self._user_agent}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_subreddit_posts(
        self, subreddit: str, sort: str = "new", limit: int = 25
    ) -> list[dict]:
        """Fetch latest posts from a subreddit.

        GET /r/{subreddit}/{sort}.json?limit={limit}

        Returns:
            List of parsed post dicts.
        """
        url = f"{_REDDIT_BASE}/r/{subreddit}/{sort}.json"
        params = {"limit": limit}

        try:
            response = self._get(url, params=params)
        except Exception as exc:
            self.logger.error(
                f"fetch_subreddit_posts failed for r/{subreddit}: {exc}"
            )
            return []

        try:
            data = response.json()
            children = data.get("data", {}).get("children", [])
            posts = []
            for child in children:
                if child.get("kind") == "t3":
                    posts.append(self._parse_post(child.get("data", {})))
            self.logger.debug(
                f"Fetched {len(posts)} posts from r/{subreddit} ({sort})"
            )
            return posts
        except Exception as exc:
            self.logger.error(
                f"Error parsing subreddit posts for r/{subreddit}: {exc}"
            )
            return []

    def fetch_post_with_comments(
        self, post_id: str, subreddit: Optional[str] = None
    ) -> dict:
        """Fetch a single post with all comments.

        GET /comments/{post_id}/.json?limit=100&depth=10

        Returns:
            {"post": {...}, "comments": [...]}
        """
        url = f"{_REDDIT_BASE}/comments/{post_id}/.json"
        params = {"limit": 100, "depth": 10}

        try:
            response = self._get(url, params=params)
        except Exception as exc:
            self.logger.error(
                f"fetch_post_with_comments failed for {post_id}: {exc}"
            )
            return {"post": {}, "comments": [], "more_comment_ids": []}

        try:
            data = response.json()
            # Reddit returns a 2-element array: [post_listing, comments_listing]
            if not isinstance(data, list) or len(data) < 2:
                self.logger.warning(
                    f"Unexpected response shape for post {post_id}"
                )
                return {"post": {}, "comments": [], "more_comment_ids": []}

            post_listing = data[0]
            comments_listing = data[1]

            # Parse the post
            post_children = (
                post_listing.get("data", {}).get("children", [])
            )
            post = {}
            if post_children and post_children[0].get("kind") == "t3":
                post = self._parse_post(post_children[0].get("data", {}))

            # Parse the comment tree
            comments, more_ids = self._parse_comments_tree(comments_listing)

            self.logger.debug(
                f"Fetched post {post_id} with {len(comments)} top-level comments"
            )
            return {"post": post, "comments": comments, "more_comment_ids": more_ids}

        except Exception as exc:
            self.logger.error(
                f"Error parsing post+comments for {post_id}: {exc}"
            )
            return {"post": {}, "comments": [], "more_comment_ids": []}

    def fetch_user_profile(self, username: str) -> Optional[dict]:
        """Fetch a Reddit user's public profile via /user/{name}/about.json.

        Returns a dict with: username, total_karma, link_karma, comment_karma,
        created_utc, account_age_days, is_gold, is_mod, has_verified_email.
        Returns None if user is deleted/suspended or request fails.
        """
        if not username or username == "[deleted]":
            return None

        url = f"{_REDDIT_BASE}/user/{username}/about.json"
        try:
            response = self._get(url)
            data = response.json().get("data", {})
            if not data.get("name"):
                return None

            created_utc = data.get("created_utc", 0)
            import time as _time
            age_days = int((_time.time() - created_utc) / 86400) if created_utc else 0

            return {
                "username": data["name"],
                "total_karma": data.get("total_karma", 0),
                "link_karma": data.get("link_karma", 0),
                "comment_karma": data.get("comment_karma", 0),
                "created_utc": created_utc,
                "account_age_days": age_days,
                "is_gold": data.get("is_gold", False),
                "is_mod": data.get("is_mod", False),
                "has_verified_email": data.get("has_verified_email", False),
            }
        except Exception as exc:
            self.logger.debug(f"Failed to fetch user profile for {username}: {exc}")
            return None

    def health_check(self) -> dict:
        """Check if Reddit is accessible.

        GET /r/all/new.json?limit=1

        Returns:
            {"status": "healthy"|"unhealthy", ...}
        """
        url = f"{_REDDIT_BASE}/r/all/new.json"
        try:
            response = self._get(url, params={"limit": 1})
            data = response.json()
            children = data.get("data", {}).get("children", [])
            return {
                "status": "healthy",
                "reddit_json_api": "accessible",
                "sample_posts_returned": len(children),
                "rate_limit_remaining": self._rate_limit_remaining,
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _handle_rate_limit(self, response: httpx.Response) -> None:
        """Read rate-limit headers and sleep if remaining < 10."""
        try:
            remaining = response.headers.get("x-ratelimit-remaining")
            reset = response.headers.get("x-ratelimit-reset")

            if remaining is not None:
                self._rate_limit_remaining = float(remaining)
            if reset is not None:
                self._rate_limit_reset = float(reset)

            if (
                self._rate_limit_remaining is not None
                and self._rate_limit_remaining < 10
            ):
                sleep_secs = (
                    self._rate_limit_reset
                    if self._rate_limit_reset is not None
                    else 60.0
                )
                self.logger.warning(
                    f"Rate limit low ({self._rate_limit_remaining} remaining). "
                    f"Sleeping {sleep_secs:.1f}s ..."
                )
                time.sleep(sleep_secs)
        except Exception as exc:
            self.logger.debug(f"_handle_rate_limit error (non-fatal): {exc}")

    def _get(
        self,
        url: str,
        params: Optional[dict] = None,
        attempt: int = 0,
    ) -> httpx.Response:
        """Perform a GET with retries and rate-limit handling."""
        try:
            response = self._client.get(url, params=params)
            self._handle_rate_limit(response)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429 and attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt * 2
                self.logger.warning(
                    f"HTTP 429 on {url}. Retry {attempt+1}/{_MAX_RETRIES} in {wait}s"
                )
                time.sleep(wait)
                return self._get(url, params=params, attempt=attempt + 1)
            raise
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                self.logger.warning(
                    f"Network error on {url}: {exc}. "
                    f"Retry {attempt+1}/{_MAX_RETRIES} in {wait}s"
                )
                time.sleep(wait)
                return self._get(url, params=params, attempt=attempt + 1)
            raise

    def _parse_post(self, post_data: dict) -> dict:
        """Parse a t3 (post) thing into a structured dict."""
        return {
            "id": post_data.get("id", ""),
            "title": post_data.get("title", ""),
            "selftext": post_data.get("selftext", ""),
            "author": post_data.get("author", "[deleted]"),
            "author_fullname": post_data.get("author_fullname", ""),
            "subreddit": post_data.get("subreddit", ""),
            "score": post_data.get("score", 0),
            "upvote_ratio": post_data.get("upvote_ratio", 0.0),
            "num_comments": post_data.get("num_comments", 0),
            "created_utc": post_data.get("created_utc", 0),
            "permalink": post_data.get("permalink", ""),
            "url": post_data.get("url", ""),
            "link_flair_text": post_data.get("link_flair_text", None),
            "is_self": post_data.get("is_self", False),
            # Fields populated later by collection pipeline
            "author_info": {
                "link_karma": 0,
                "comment_karma": 0,
                "created_utc": 0,
            },
            "relevance_score": 0.0,
            "matched_keywords": [],
            "comments": [],
            "more_comment_ids": [],
        }

    def _parse_comment(self, comment_data: dict, depth: int = 0) -> dict:
        """Parse a t1 (comment) thing into a structured dict.

        Recursively parses replies. Collects IDs from 'more' stubs.
        """
        replies_raw = comment_data.get("replies", "")
        parsed_replies = []
        more_ids: list[str] = []

        if isinstance(replies_raw, dict):
            nested_comments, nested_more = self._parse_comments_tree(replies_raw)
            parsed_replies = nested_comments
            more_ids.extend(nested_more)

        return {
            "id": comment_data.get("id", ""),
            "body": comment_data.get("body", ""),
            "author": comment_data.get("author", "[deleted]"),
            "score": comment_data.get("score", 0),
            "created_utc": comment_data.get("created_utc", 0),
            "parent_id": comment_data.get("parent_id", ""),
            "depth": depth,
            "is_submitter": comment_data.get("is_submitter", False),
            "replies": parsed_replies,
            # more_ids from nested replies are surfaced to the caller via
            # _parse_comments_tree; stored here for completeness
            "_more_ids": more_ids,
        }

    def _parse_comments_tree(
        self, comments_listing: dict
    ) -> tuple[list[dict], list[str]]:
        """Parse a comments listing object into (comments, more_ids).

        Recursively parses nested replies.
        """
        comments: list[dict] = []
        more_ids: list[str] = []

        children = comments_listing.get("data", {}).get("children", [])

        for child in children:
            kind = child.get("kind")
            data = child.get("data", {})

            if kind == "t1":
                depth = data.get("depth", 0)
                comment = self._parse_comment(data, depth=depth)
                # Collect more_ids surfaced from nested levels
                more_ids.extend(comment.pop("_more_ids", []))
                comments.append(comment)

            elif kind == "more":
                # Collect IDs of unexpanded comment stubs
                stub_ids = data.get("children", [])
                more_ids.extend(stub_ids)

        return comments, more_ids


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Reddit JSON Collector")
    parser.add_argument("--health", action="store_true", help="Health check")
    parser.add_argument("--subreddit", type=str, default="HomeNetworking")
    parser.add_argument("--limit", type=int, default=5)
    args = parser.parse_args()

    collector = RedditJsonCollector()

    if args.health:
        result = collector.health_check()
        print(json.dumps(result, indent=2))
    else:
        posts = collector.fetch_subreddit_posts(
            args.subreddit, sort="new", limit=args.limit
        )
        print(f"Fetched {len(posts)} posts from r/{args.subreddit}")
        for p in posts[:3]:
            print(f"  [{p['score']:>5}] {p['title'][:70]}")
