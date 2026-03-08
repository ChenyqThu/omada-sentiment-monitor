"""
Reddit JSON Collector
Fetches Reddit data using the public .json endpoint via httpx (no PRAW dependency).
"""
import re
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

    def search_subreddit(
        self,
        subreddit: str,
        query: str,
        sort: str = "relevance",
        time_filter: str = "week",
        limit: int = 25,
    ) -> list[dict]:
        """Search within a subreddit.

        GET /r/{subreddit}/search.json?q={query}&restrict_sr=on&sort={sort}&t={time_filter}&limit={limit}

        Returns:
            List of parsed post dicts.
        """
        url = f"{_REDDIT_BASE}/r/{subreddit}/search.json"
        params = {
            "q": query,
            "restrict_sr": "on",
            "sort": sort,
            "t": time_filter,
            "limit": limit,
        }

        try:
            response = self._get(url, params=params)
        except Exception as exc:
            self.logger.error(
                f"search_subreddit failed for r/{subreddit} query={query!r}: {exc}"
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
                f"Search r/{subreddit} query={query!r} returned {len(posts)} posts"
            )
            return posts
        except Exception as exc:
            self.logger.error(
                f"Error parsing search results for r/{subreddit}: {exc}"
            )
            return []

    def expand_more_comments(
        self, post_id: str, children: list[str]
    ) -> list[dict]:
        """Expand 'more' comment stubs.

        GET /api/morechildren.json?link_id=t3_{post_id}&children={comma_joined}&api_type=json

        Returns:
            List of parsed comment dicts.
        """
        if not children:
            return []

        url = f"{_REDDIT_BASE}/api/morechildren.json"
        params = {
            "link_id": f"t3_{post_id}",
            "children": ",".join(children),
            "api_type": "json",
        }

        try:
            response = self._get(url, params=params)
        except Exception as exc:
            self.logger.error(
                f"expand_more_comments failed for post {post_id}: {exc}"
            )
            return []

        try:
            data = response.json()
            things = (
                data.get("json", {})
                .get("data", {})
                .get("things", [])
            )
            comments = []
            for thing in things:
                kind = thing.get("kind")
                if kind == "t1":
                    comments.append(
                        self._parse_comment(thing.get("data", {}), depth=0)
                    )
            self.logger.debug(
                f"Expanded {len(comments)} comments for post {post_id}"
            )
            return comments
        except Exception as exc:
            self.logger.error(
                f"Error parsing morechildren for post {post_id}: {exc}"
            )
            return []

    def collect_relevant_posts(
        self,
        subreddits: list[str],
        primary_keywords: list[str],
        secondary_keywords: list[str],
        competitor_keywords: list[str],
        max_per_sub: int = 25,
    ) -> list[dict]:
        """Main collection method.

        Fetches posts from multiple subreddits, filters by keyword relevance,
        fetches full comments for relevant posts.

        Only posts with relevance_score > 0 are included.
        Comments are fetched for posts where influence_score > 3.0 OR num_comments > 5.

        Returns:
            List of post dicts with complete comment trees.
        """
        compiled = self._compile_keywords(
            primary_keywords, secondary_keywords, competitor_keywords
        )

        all_posts = []

        for subreddit in subreddits:
            self.logger.info(f"Collecting from r/{subreddit} ...")
            raw_posts = self.fetch_subreddit_posts(
                subreddit, sort="new", limit=max_per_sub
            )

            for post in raw_posts:
                full_text = f"{post.get('title', '')} {post.get('selftext', '')}"
                matched, relevance_score = self._match_keywords(full_text, compiled)

                if relevance_score <= 0:
                    continue

                post["relevance_score"] = relevance_score
                post["matched_keywords"] = matched

                # Calculate influence score (same logic as existing collector)
                influence = self.calculate_influence_score(post)
                post["influence_score"] = influence

                all_posts.append(post)

        self.logger.info(
            f"Found {len(all_posts)} relevant posts across {len(subreddits)} subreddit(s)"
        )

        # Fetch full comments for important posts
        for post in all_posts:
            needs_comments = (
                post.get("influence_score", 0) > 3.0
                or post.get("num_comments", 0) > 5
            )
            if needs_comments:
                try:
                    result = self.fetch_post_with_comments(post["id"])
                    post["comments"] = result.get("comments", [])
                    post["more_comment_ids"] = result.get("more_comment_ids", [])
                    self.logger.debug(
                        f"Fetched {len(post['comments'])} comments for post {post['id']}"
                    )
                except Exception as exc:
                    self.logger.warning(
                        f"Failed to fetch comments for post {post['id']}: {exc}"
                    )
                    post.setdefault("comments", [])
                    post.setdefault("more_comment_ids", [])
            else:
                post.setdefault("comments", [])
                post.setdefault("more_comment_ids", [])

        return all_posts

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
    # KOL / influence scoring (ported from RedditCollector)
    # ------------------------------------------------------------------

    def calculate_kol_score(self, author_info: dict) -> float:
        """Calculate KOL score for a user.

        Scoring breakdown (max 100):
          - Karma score    0-30  (1 pt per 1000 total karma, max 30)
          - Age score      0-10  (2 pts per year, max 10)
          - Activity score 0-20  (0.5 pts per recent post/comment, max 20)
          - Quality score  0-20  (avg of avg_post_score + avg_comment_score, max 20)
          - Tech focus     0-20  (tech_focus_score * 20)
          - Special bonus       (+5 verified, +3 gold, +5 mod)
        """
        try:
            score = 0.0

            total_karma = author_info.get("total_karma", 0)
            if total_karma == 0:
                total_karma = (
                    author_info.get("link_karma", 0)
                    + author_info.get("comment_karma", 0)
                )
            karma_score = min(total_karma / 1000, 30)

            account_age = author_info.get("account_age_days", 0)
            if account_age == 0 and author_info.get("created_utc"):
                account_age = max(
                    0,
                    (time.time() - author_info["created_utc"]) / 86400,
                )
            age_score = min(account_age / 365 * 2, 10)

            recent_activity = (
                author_info.get("recent_posts_count", 0)
                + author_info.get("recent_comments_count", 0)
            )
            activity_score = min(recent_activity * 0.5, 20)

            avg_post_score = author_info.get("avg_post_score", 0)
            avg_comment_score = author_info.get("avg_comment_score", 0)
            quality_score = min((avg_post_score + avg_comment_score) / 2, 20)

            tech_focus = author_info.get("tech_focus_score", 0)
            tech_score = tech_focus * 20

            special_bonus = 0.0
            if author_info.get("verified"):
                special_bonus += 5
            if author_info.get("is_gold"):
                special_bonus += 3
            if author_info.get("is_mod"):
                special_bonus += 5

            total = (
                karma_score
                + age_score
                + activity_score
                + quality_score
                + tech_score
                + special_bonus
            )
            return round(min(total, 100.0), 2)

        except Exception as exc:
            self.logger.error(f"calculate_kol_score failed: {exc}")
            return 0.0

    def calculate_influence_score(self, post: dict) -> float:
        """Calculate influence score for a post.

        Formula mirrors the existing collector:
          (score*0.4 + num_comments*0.3 + author_factor) * subreddit_weight * relevance_weight

        Subreddit weights are imported from config if available; otherwise default 1.0.
        """
        try:
            base_score = post.get("score", 0) * 0.4
            engagement = post.get("num_comments", 0) * 0.3

            # Author karma factor
            author_info = post.get("author_info") or {}
            total_karma = author_info.get("total_karma", 0)
            if total_karma == 0:
                total_karma = (
                    author_info.get("link_karma", 0)
                    + author_info.get("comment_karma", 0)
                )
            author_factor = min(total_karma * 0.0001, 10)

            # Subreddit weight
            try:
                from config.settings import SUBREDDIT_WEIGHTS
                subreddit_weight = SUBREDDIT_WEIGHTS.get(
                    post.get("subreddit", ""), 1.0
                )
            except Exception:
                subreddit_weight = 1.0

            relevance_weight = post.get("relevance_score", 1.0)

            influence = (
                (base_score + engagement + author_factor)
                * subreddit_weight
                * relevance_weight
            )
            return round(influence, 2)

        except Exception as exc:
            self.logger.error(f"calculate_influence_score failed: {exc}")
            return 0.0

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

    # ------------------------------------------------------------------
    # Keyword helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _compile_keywords(
        primary: list[str],
        secondary: list[str],
        competitor: list[str],
    ) -> dict[str, list]:
        """Compile keyword lists into regex patterns keyed by category."""
        result: dict[str, list] = {
            "primary_keywords": [],
            "secondary_keywords": [],
            "competitor_keywords": [],
        }
        mapping = {
            "primary_keywords": primary,
            "secondary_keywords": secondary,
            "competitor_keywords": competitor,
        }
        for category, keywords in mapping.items():
            for kw in keywords:
                try:
                    pattern = re.compile(
                        r"\b" + re.escape(kw.strip()) + r"\b",
                        re.IGNORECASE,
                    )
                    result[category].append(pattern)
                except re.error:
                    pass
        return result

    @staticmethod
    def _match_keywords(
        text: str,
        compiled: dict[str, list],
    ) -> tuple[list[str], float]:
        """Match compiled keyword patterns against text.

        Returns:
            (matched_keywords, relevance_score)
        """
        weights = {
            "primary_keywords": 1.0,
            "secondary_keywords": 0.7,
            "competitor_keywords": 0.5,
        }

        matched: list[str] = []
        relevance_score = 0.0

        for category, patterns in compiled.items():
            weight = weights.get(category, 0.5)
            for pattern in patterns:
                hits = pattern.findall(text)
                if hits:
                    keyword = pattern.pattern.replace(r"\b", "").replace("\\", "")
                    matched.append(keyword)
                    relevance_score += len(hits) * weight

        # Normalise to 0-1
        max_possible = len(compiled.get("primary_keywords", [])) * 1.0
        if max_possible > 0:
            relevance_score = min(relevance_score / max_possible, 1.0)

        return list(set(matched)), relevance_score


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
