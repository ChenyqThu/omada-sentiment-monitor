"""
YouTube Data API v3 Collector
Fetches YouTube data using the REST API via httpx (no google-api-python-client dependency).
"""
import time
import os
import sys
from datetime import datetime, timezone
from typing import Optional

import httpx

project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from src.utils.logger import LoggerMixin

_API_BASE = "https://www.googleapis.com/youtube/v3"
_MAX_RETRIES = 3
_BACKOFF_BASE = 2.0


class YouTubeCollector(LoggerMixin):
    """YouTube data collector using the Data API v3 via httpx."""

    def __init__(self, api_key: str, quota_tracker=None):
        """
        Args:
            api_key: YouTube Data API v3 key.
            quota_tracker: Optional callable(units, is_search) for quota tracking.
        """
        self._api_key = api_key
        self._quota_tracker = quota_tracker
        self._client = httpx.Client(
            headers={"Accept": "application/json"},
            follow_redirects=True,
            timeout=30.0,
        )
        self.logger.info("YouTubeCollector initialized")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def search_videos(
        self, query: str, max_results: int = 10, published_after: str = None,
    ) -> list[dict]:
        """Search for videos by keyword. Costs 100 quota units per call.

        Args:
            query: Search query string.
            max_results: Max results per page (max 50).
            published_after: ISO 8601 datetime string for incremental search.

        Returns:
            List of video dicts with basic info (need get_video_details for full stats).
        """
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": "date",
            "maxResults": min(max_results, 50),
        }
        if published_after:
            params["publishedAfter"] = published_after

        try:
            data = self._get("search", params=params, quota_cost=100, is_search=True)
        except Exception as exc:
            self.logger.error(f"search_videos failed for '{query}': {exc}")
            return []

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = item.get("id", {}).get("videoId", "")
            if not video_id:
                continue
            videos.append({
                "id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "discovered_via": "search",
            })

        self.logger.debug(f"Search '{query}': {len(videos)} videos found")
        return videos

    def get_video_details(self, video_ids: list[str]) -> list[dict]:
        """Get full details for videos. Costs 1 quota unit per call (up to 50 IDs per call).

        Args:
            video_ids: List of YouTube video IDs.

        Returns:
            List of video dicts with full statistics.
        """
        all_details = []
        # Process in batches of 50
        for i in range(0, len(video_ids), 50):
            batch = video_ids[i:i + 50]
            params = {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
            }
            try:
                data = self._get("videos", params=params, quota_cost=1)
            except Exception as exc:
                self.logger.error(f"get_video_details failed: {exc}")
                continue

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})
                all_details.append({
                    "id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "channel_id": snippet.get("channelId", ""),
                    "channel_title": snippet.get("channelTitle", ""),
                    "published_at": snippet.get("publishedAt", ""),
                    "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                    "tags": snippet.get("tags", []),
                    "category_id": snippet.get("categoryId", ""),
                    "duration": content.get("duration", ""),
                    "view_count": int(stats.get("viewCount", 0)),
                    "like_count": int(stats.get("likeCount", 0)),
                    "comment_count": int(stats.get("commentCount", 0)),
                    "url": f"https://www.youtube.com/watch?v={item.get('id', '')}",
                })

        return all_details

    def get_channel_details(self, channel_ids: list[str]) -> list[dict]:
        """Get channel details. Costs 1 quota unit per call.

        Args:
            channel_ids: List of channel IDs.

        Returns:
            List of channel detail dicts.
        """
        all_channels = []
        for i in range(0, len(channel_ids), 50):
            batch = channel_ids[i:i + 50]
            params = {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(batch),
            }
            try:
                data = self._get("channels", params=params, quota_cost=1)
            except Exception as exc:
                self.logger.error(f"get_channel_details failed: {exc}")
                continue

            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})
                uploads_id = content.get("relatedPlaylists", {}).get("uploads", "")
                all_channels.append({
                    "id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "custom_url": snippet.get("customUrl", ""),
                    "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    "subscriber_count": int(stats.get("subscriberCount", 0)),
                    "video_count": int(stats.get("videoCount", 0)),
                    "view_count": int(stats.get("viewCount", 0)),
                    "uploads_playlist_id": uploads_id,
                })

        return all_channels

    def resolve_handles(self, handles: list[str]) -> list[dict]:
        """Resolve @handle format to channel details.

        Args:
            handles: List of handles (e.g. ['@UbiquitiInc', '@SPXLabs']).

        Returns:
            List of channel dicts with id, title, uploads_playlist_id, etc.
        """
        channels = []
        for handle in handles:
            # Strip @ if present
            clean_handle = handle.lstrip("@")
            params = {
                "part": "snippet,statistics,contentDetails",
                "forHandle": clean_handle,
            }
            try:
                data = self._get("channels", params=params, quota_cost=1)
                items = data.get("items", [])
                if not items:
                    self.logger.warning(f"Handle @{clean_handle} not found")
                    continue

                item = items[0]
                snippet = item.get("snippet", {})
                stats = item.get("statistics", {})
                content = item.get("contentDetails", {})
                uploads_id = content.get("relatedPlaylists", {}).get("uploads", "")

                channels.append({
                    "id": item.get("id", ""),
                    "title": snippet.get("title", ""),
                    "description": snippet.get("description", ""),
                    "custom_url": snippet.get("customUrl", ""),
                    "thumbnail_url": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
                    "subscriber_count": int(stats.get("subscriberCount", 0)),
                    "video_count": int(stats.get("videoCount", 0)),
                    "view_count": int(stats.get("viewCount", 0)),
                    "uploads_playlist_id": uploads_id,
                    "is_monitored": True,
                    "handle": handle,
                })
                self.logger.debug(f"Resolved @{clean_handle} → {item.get('id', '')}")

            except Exception as exc:
                self.logger.error(f"resolve_handles failed for @{clean_handle}: {exc}")

        return channels

    def get_channel_uploads(
        self, uploads_playlist_id: str, max_results: int = 10,
    ) -> list[dict]:
        """Get recent uploads from a channel's uploads playlist.
        Costs 1 quota unit per call.

        Args:
            uploads_playlist_id: The uploads playlist ID (UU...).
            max_results: Number of recent videos to fetch.

        Returns:
            List of video dicts (basic info only, need get_video_details for stats).
        """
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist_id,
            "maxResults": min(max_results, 50),
        }
        try:
            data = self._get("playlistItems", params=params, quota_cost=1)
        except Exception as exc:
            self.logger.error(f"get_channel_uploads failed for {uploads_playlist_id}: {exc}")
            return []

        videos = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            video_id = snippet.get("resourceId", {}).get("videoId", "")
            if not video_id:
                continue
            videos.append({
                "id": video_id,
                "title": snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "channel_id": snippet.get("channelId", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": snippet.get("publishedAt", ""),
                "thumbnail_url": snippet.get("thumbnails", {}).get("high", {}).get("url", ""),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "discovered_via": "channel_monitor",
            })

        return videos

    def get_video_comments(
        self, video_id: str, max_results: int = 100,
    ) -> list[dict]:
        """Get top-level comment threads for a video.
        Costs 1 quota unit per call.

        Args:
            video_id: YouTube video ID.
            max_results: Max comments to fetch.

        Returns:
            List of comment dicts (includes replies).
        """
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": min(max_results, 100),
            "order": "relevance",
            "textFormat": "plainText",
        }
        try:
            data = self._get("commentThreads", params=params, quota_cost=1)
        except Exception as exc:
            self.logger.error(f"get_video_comments failed for {video_id}: {exc}")
            return []

        comments = []
        for item in data.get("items", []):
            top_comment = item.get("snippet", {}).get("topLevelComment", {})
            tc_snippet = top_comment.get("snippet", {})

            comments.append({
                "id": top_comment.get("id", item.get("id", "")),
                "video_id": video_id,
                "parent_id": "",
                "author": tc_snippet.get("authorDisplayName", ""),
                "author_channel_id": tc_snippet.get("authorChannelId", {}).get("value", ""),
                "text": tc_snippet.get("textDisplay", ""),
                "like_count": tc_snippet.get("likeCount", 0),
                "published_at": tc_snippet.get("publishedAt", ""),
                "is_reply": False,
            })

            # Include replies
            replies = item.get("replies", {}).get("comments", [])
            for reply in replies:
                r_snippet = reply.get("snippet", {})
                comments.append({
                    "id": reply.get("id", ""),
                    "video_id": video_id,
                    "parent_id": top_comment.get("id", ""),
                    "author": r_snippet.get("authorDisplayName", ""),
                    "author_channel_id": r_snippet.get("authorChannelId", {}).get("value", ""),
                    "text": r_snippet.get("textDisplay", ""),
                    "like_count": r_snippet.get("likeCount", 0),
                    "published_at": r_snippet.get("publishedAt", ""),
                    "is_reply": True,
                })

        self.logger.debug(f"Fetched {len(comments)} comments for video {video_id}")
        return comments

    def health_check(self) -> dict:
        """Verify API key is valid by making a cheap API call."""
        params = {
            "part": "snippet",
            "chart": "mostPopular",
            "maxResults": 1,
            "regionCode": "US",
        }
        try:
            data = self._get("videos", params=params, quota_cost=1)
            items = data.get("items", [])
            return {
                "status": "healthy",
                "youtube_api": "accessible",
                "sample_returned": len(items),
            }
        except Exception as exc:
            return {
                "status": "unhealthy",
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get(
        self,
        endpoint: str,
        params: dict = None,
        quota_cost: int = 1,
        is_search: bool = False,
        attempt: int = 0,
    ) -> dict:
        """Perform a GET request to YouTube API with retries and quota tracking."""
        if params is None:
            params = {}
        params["key"] = self._api_key

        url = f"{_API_BASE}/{endpoint}"

        try:
            response = self._client.get(url, params=params)
            response.raise_for_status()

            # Track quota
            if self._quota_tracker:
                self._quota_tracker(quota_cost, is_search)

            return response.json()

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 403:
                # Check if quota exceeded
                try:
                    error_data = exc.response.json()
                    errors = error_data.get("error", {}).get("errors", [])
                    for e in errors:
                        if e.get("reason") == "quotaExceeded":
                            self.logger.error("YouTube API daily quota exceeded!")
                            raise
                except (ValueError, KeyError):
                    pass

            if status == 429 and attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt * 2
                self.logger.warning(
                    f"HTTP 429 on {endpoint}. Retry {attempt+1}/{_MAX_RETRIES} in {wait}s"
                )
                time.sleep(wait)
                return self._get(endpoint, params, quota_cost, is_search, attempt + 1)
            raise

        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            if attempt < _MAX_RETRIES:
                wait = _BACKOFF_BASE ** attempt
                self.logger.warning(
                    f"Network error on {endpoint}: {exc}. "
                    f"Retry {attempt+1}/{_MAX_RETRIES} in {wait}s"
                )
                time.sleep(wait)
                return self._get(endpoint, params, quota_cost, is_search, attempt + 1)
            raise
