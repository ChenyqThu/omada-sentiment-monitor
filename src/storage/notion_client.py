"""
Notion API 客户端
负责将 Pipeline 数据（帖子、KOL）同步到 Notion Database
"""
import os
import sys
import json
import requests as http_requests
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import notion_config
from src.utils.logger import LoggerMixin

try:
    from notion_client import Client
    from notion_client.errors import APIResponseError
except ImportError:
    Client = None
    APIResponseError = Exception


class NotionSyncClient(LoggerMixin):
    """Notion 同步客户端"""

    def __init__(self):
        super().__init__()

        if Client is None:
            raise ImportError("请安装 notion-client 库: pip install notion-client")

        if not notion_config.token:
            raise ValueError("Notion Token 未配置，请设置 NOTION_TOKEN 环境变量")

        if not notion_config.database_id:
            raise ValueError("Notion Database ID 未配置，请设置 NOTION_DATABASE_ID 环境变量")

        # 初始化 Notion 客户端
        self.client = Client(auth=notion_config.token)
        self.database_id = notion_config.database_id

        # 缓存 Database 结构
        self._database_schema = None

        self.logger.info(f"Notion 客户端初始化完成")
        self.logger.info(f"Database ID: {self.database_id[:8]}...")

    def health_check(self) -> Dict[str, Any]:
        """检查 Notion 连通性"""
        try:
            self._get_database_schema()
            return {"status": "healthy", "database_id": self.database_id[:8]}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}

    # ------------------------------------------------------------------
    # Schema & property helpers
    # ------------------------------------------------------------------

    def _get_database_schema(self) -> Dict[str, Any]:
        """获取 Database 结构"""
        if self._database_schema is None:
            try:
                response = self.client.databases.retrieve(database_id=self.database_id)
                self._database_schema = response.get('properties', {})
                self.logger.info(f"获取到 Database 结构，包含 {len(self._database_schema)} 个字段")
            except Exception as e:
                self.logger.error(f"获取 Database 结构失败: {e}")
                raise

        return self._database_schema

    def _format_property_value(self, property_name: str, value: Any) -> Optional[Dict[str, Any]]:
        """根据 Database schema 自动格式化属性值"""
        schema = self._get_database_schema()
        prop_config = schema.get(property_name, {})
        prop_type = prop_config.get('type', 'rich_text')

        if value is None:
            return None

        try:
            if prop_type == 'title':
                return {'title': [{'text': {'content': str(value)[:2000]}}]}
            elif prop_type == 'rich_text':
                return {'rich_text': [{'text': {'content': str(value)[:2000]}}]}
            elif prop_type == 'number':
                return {'number': float(value) if value is not None else None}
            elif prop_type == 'select':
                return {'select': {'name': str(value)} if value else None}
            elif prop_type == 'status':
                return {'status': {'name': str(value)} if value else None}
            elif prop_type == 'multi_select':
                if isinstance(value, (list, tuple)):
                    return {'multi_select': [{'name': str(v)} for v in value if v]}
                elif isinstance(value, str):
                    items = [item.strip() for item in value.split(',') if item.strip()]
                    return {'multi_select': [{'name': item} for item in items]}
                else:
                    return {'multi_select': [{'name': str(value)}] if value else []}
            elif prop_type == 'checkbox':
                return {'checkbox': bool(value)}
            elif prop_type == 'date':
                if isinstance(value, datetime):
                    return {'date': {'start': value.isoformat()}}
                elif isinstance(value, str):
                    return {'date': {'start': value}}
                else:
                    return None
            elif prop_type == 'url':
                return {'url': str(value) if value else None}
            else:
                return {'rich_text': [{'text': {'content': str(value)[:2000]}}]}

        except Exception as e:
            self.logger.warning(f"格式化属性 {property_name} 失败: {e}，使用默认格式")
            return {'rich_text': [{'text': {'content': str(value)[:2000]}}]}

    # ------------------------------------------------------------------
    # Markdown API helpers
    # ------------------------------------------------------------------

    def _notion_markdown_request(
        self, method: str, url: str, headers: dict, json: dict = None, timeout: int = 30
    ) -> http_requests.Response:
        """Send a Notion Markdown API request with 429 retry."""
        max_retries = 3
        for attempt in range(max_retries):
            if method == "GET":
                resp = http_requests.get(url, headers=headers, timeout=timeout)
            else:
                resp = http_requests.patch(url, headers=headers, json=json, timeout=timeout)

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 2 * (attempt + 1)))
                self.logger.warning(f"Notion 429 限流，{retry_after}s 后重试 ({attempt+1}/{max_retries})")
                import time
                time.sleep(retry_after)
                continue

            resp.raise_for_status()
            return resp

        # Last attempt failed with 429
        resp.raise_for_status()
        return resp

    def _write_page_markdown(self, page_id: str, markdown: str) -> bool:
        """通过 Notion Markdown API 写入页面内容 (insert_content)。

        Requires Notion-Version >= 2025-09-03.
        """
        url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
        headers = {
            "Authorization": f"Bearer {notion_config.token}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        }
        payload = {
            "type": "insert_content",
            "insert_content": {"content": markdown},
        }
        try:
            self._notion_markdown_request("PATCH", url, headers, json=payload)
            self.logger.debug(f"Markdown API 写入成功: page {page_id} ({len(markdown)} chars)")
            return True
        except http_requests.HTTPError as exc:
            self.logger.error(f"Markdown API 写入失败: {exc} — {exc.response.text if exc.response else ''}")
            return False
        except Exception as exc:
            self.logger.error(f"Markdown API 请求异常: {exc}")
            return False

    def _replace_page_markdown(self, page_id: str, markdown: str) -> bool:
        """读取现有内容并整体替换 (replace_content_range)。"""
        url = f"https://api.notion.com/v1/pages/{page_id}/markdown"
        headers = {
            "Authorization": f"Bearer {notion_config.token}",
            "Notion-Version": "2025-09-03",
            "Content-Type": "application/json",
        }
        try:
            read_resp = self._notion_markdown_request("GET", url, headers, timeout=15)
            current = read_resp.json().get("markdown", "")

            if not current.strip():
                # Try insert first; if it fails (e.g. page has empty blocks),
                # fall through to replace with the raw current as content_range.
                if self._write_page_markdown(page_id, markdown):
                    return True
                # Use whatever was returned (even whitespace) as content_range
                if not current:
                    return False

            payload = {
                "type": "replace_content_range",
                "replace_content_range": {
                    "content": markdown,
                    "content_range": current,
                    "allow_deleting_content": True,
                },
            }
            self._notion_markdown_request("PATCH", url, headers, json=payload)
            self.logger.debug(f"Markdown API 替换成功: page {page_id}")
            return True
        except http_requests.HTTPError as exc:
            self.logger.error(f"Markdown API 替换失败: {exc} — {exc.response.text if exc.response else ''}")
            return False
        except Exception as exc:
            self.logger.error(f"Markdown API 替换异常: {exc}")
            return False

    # ==================================================================
    # Post Sync: sync post dicts (from SQLite) to Notion posts database
    # ==================================================================

    def _find_existing_page(self, reddit_id: str) -> Optional[Dict[str, Any]]:
        """查找是否已存在相同 Reddit ID 的帖子"""
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Reddit ID",
                    "rich_text": {"equals": reddit_id},
                },
                page_size=1,
            )
            results = response.get('results', [])
            if results:
                self.logger.debug(f"找到已存在的帖子: {reddit_id}")
                return results[0]
            return None
        except Exception as e:
            self.logger.warning(f"查找已存在页面失败: {e}")
            return None

    def sync_post_from_dict(self, post: dict) -> Optional[str]:
        """Sync a post dict (from SQLite with comments) to Notion.

        Returns the Notion page ID on success, None on failure.
        """
        reddit_id = post.get("id", "")
        if not reddit_id:
            self.logger.error("Post dict missing 'id'")
            return None

        try:
            existing = self._find_existing_page(reddit_id)
            properties = self._build_properties_from_dict(post)

            if existing:
                page_id = existing["id"]
                self.client.pages.update(page_id=page_id, properties=properties)

                # Check if comments changed — if so, replace page content
                old_comments = self._get_page_comment_count(existing)
                new_comments = len(post.get("comments", []))
                if new_comments != old_comments:
                    markdown = self._build_markdown_from_dict(post)
                    if markdown:
                        self._replace_page_markdown(page_id, markdown)
                    self.logger.info(f"更新 Notion 页面 (含内容): {page_id}")
                else:
                    self.logger.info(f"更新 Notion 页面 (仅属性): {page_id}")
            else:
                response = self.client.pages.create(
                    parent={"database_id": self.database_id},
                    properties=properties,
                )
                page_id = response["id"]
                self.logger.info(f"创建 Notion 页面: {page_id}")

                markdown = self._build_markdown_from_dict(post)
                if markdown:
                    self._write_page_markdown(page_id, markdown)

            return page_id

        except Exception as e:
            self.logger.error(f"sync_post_from_dict 失败 [{reddit_id}]: {e}")
            return None

    def _get_page_comment_count(self, page: dict) -> int:
        """Extract comment count from an existing Notion page's properties."""
        props = page.get("properties", {})
        num_prop = props.get("评论数", {})
        return num_prop.get("number", 0) or 0

    def _build_properties_from_dict(self, post: dict) -> Dict[str, Any]:
        """Build Notion properties from a SQLite post dict."""
        from datetime import datetime as _dt, timezone as _tz

        created = _dt.fromtimestamp(post.get("created_utc", 0), tz=_tz.utc)
        now = _dt.now(_tz.utc)
        week_str = now.strftime("%G-W%V")

        sentiment_map = {
            "positive": "正面", "negative": "负面",
            "neutral": "中性", "mixed": "混合",
        }
        topic_map = {
            "product_issue": "技术问题", "feature_request": "功能需求",
            "deployment": "部署案例", "comparison": "竞品对比",
            "recommendation_ask": "产品推荐", "firmware_update": "固件更新",
            "general_discussion": "一般讨论", "competitor_intel": "竞品情报",
            "positive_feedback": "正面反馈", "negative_feedback": "负面反馈",
            "not_relevant": "低相关",
        }

        ai_sentiment = post.get("ai_sentiment_quick", "neutral")
        ai_topic = post.get("ai_topic_category", "")
        ai_relevance = post.get("ai_relevance_score", 0.0) or 0.0

        sentiment_score_map = {
            "positive": 0.6, "negative": -0.6,
            "neutral": 0.0, "mixed": 0.0,
        }

        property_mappings = {
            "标题": post.get("title", ""),
            "内容": (post.get("selftext", "") or "")[:500],
            "类型": "Post",
            "来源": "Reddit",
            "Reddit ID": post["id"],
            "Subreddit": f'r/{post.get("subreddit", "")}',
            "作者": post.get("author", "[deleted]"),
            "分数": post.get("score", 0),
            "评论数": post.get("num_comments", 0),
            "发布时间": created,
            "采集时间": now,
            "最后更新时间": now,
            "Reddit链接": f'https://www.reddit.com{post.get("permalink", "")}',
            "相关性得分": ai_relevance,
            "周报周期": week_str,
            "情感倾向": sentiment_map.get(ai_sentiment, "中性"),
            "情感分数_数值": sentiment_score_map.get(ai_sentiment, 0.0),
            "AI摘要": post.get("ai_brief_reason", ""),
        }

        if ai_topic and ai_topic != "not_relevant":
            cn_topic = topic_map.get(ai_topic, ai_topic)
            property_mappings["主题分类"] = cn_topic

        # Alert level
        score_val = post.get("score", 0) or 0
        comments_val = post.get("num_comments", 0) or 0
        alert_level = "none"
        if ai_sentiment == "negative" and (score_val > 20 or comments_val > 15):
            alert_level = "critical"
        elif ai_sentiment == "negative" and (score_val > 5 or comments_val > 5):
            alert_level = "high"
        elif ai_sentiment == "negative":
            alert_level = "medium"
        property_mappings["预警等级"] = alert_level

        # Priority
        priority = "低"
        if ai_relevance >= 0.8 and (score_val > 10 or comments_val > 10):
            priority = "高"
        elif ai_relevance >= 0.5:
            priority = "中"
        property_mappings["优先级"] = priority
        property_mappings["处理状态"] = "未处理"

        properties = {}
        for prop_name, value in property_mappings.items():
            formatted = self._format_property_value(prop_name, value)
            if formatted is not None:
                properties[prop_name] = formatted

        return properties

    def _build_markdown_from_dict(self, post: dict) -> str:
        """Build markdown content from a SQLite post dict with comments."""
        lines = []

        lines.append("## 📋 帖子信息")
        lines.append("")
        lines.append(f"作者: u/{post.get('author', '[deleted]')}")
        lines.append("")

        created_utc = post.get("created_utc", 0)
        if created_utc:
            from datetime import datetime as _dt, timezone as _tz
            created = _dt.fromtimestamp(created_utc, tz=_tz.utc)
            lines.append(f"发布时间: {created.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        lines.append("")

        score = post.get("score", 0)
        num_comments = post.get("num_comments", 0)
        upvote_ratio = post.get("upvote_ratio", 0)
        lines.append(f"分数: {score} | 评论数: {num_comments} | 赞同率: {upvote_ratio:.0%}")
        lines.append("")

        ai_reason = post.get("ai_brief_reason", "")
        ai_topic = post.get("ai_topic_category", "")
        ai_sentiment = post.get("ai_sentiment_quick", "")
        ai_relevance = post.get("ai_relevance_score", 0)
        if ai_reason:
            lines.append(f"**AI 初筛**: {ai_reason} (相关性: {ai_relevance:.2f}, 话题: {ai_topic}, 情感: {ai_sentiment})")
            lines.append("")

        lines.append("## 📝 帖子内容")
        lines.append("")
        selftext = post.get("selftext", "") or ""
        if selftext.strip():
            lines.append(selftext.strip())
        else:
            lines.append("（仅标题帖子，无正文内容）")
        lines.append("")

        comments = post.get("comments", [])
        if comments:
            lines.append(f"## 💬 评论 ({len(comments)} 条)")
            lines.append("")
            self._build_flat_comments_markdown(comments, lines)

        return "\n".join(lines)

    def _build_flat_comments_markdown(self, comments: list, lines: list) -> None:
        """Build markdown from flat comment list using Notion enhanced markdown.

        Uses <details> (toggle) for each comment to keep the page clean.
        Depth is indicated by tab indentation inside parent toggles.
        """
        for c in comments:
            depth = c.get("depth", 0)
            indent = "\t" * depth

            author = c.get("author", "[deleted]")
            score = c.get("score", 0)
            body = (c.get("body", "") or "").strip()

            lines.append(f"{indent}<details>")
            lines.append(f"{indent}<summary>💬 u/{author} (分数: {score})</summary>")
            lines.append(f"")
            if body:
                for bline in body.split("\n"):
                    lines.append(f"{indent}\t{bline}")
            else:
                lines.append(f"{indent}\t（空评论）")
            lines.append(f"")
            lines.append(f"{indent}</details>")
            lines.append("")

    # ==================================================================
    # Hot Post Update: update existing Notion pages for trending posts
    # ==================================================================

    def update_hot_post(self, post: dict) -> bool:
        """Update a hot post's Notion page: refresh stats and reset 处理状态 to 未处理.

        Args:
            post: Post dict from SQLite (must have notion_page_id).

        Returns:
            True on success, False on failure.
        """
        page_id = post.get("notion_page_id")
        if not page_id:
            self.logger.warning(f"Hot post {post.get('id')} has no notion_page_id")
            return False

        try:
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)

            prev_score = post.get("prev_score", 0) or 0
            prev_comments = post.get("prev_num_comments", 0) or 0
            new_score = post.get("score", 0) or 0
            new_comments = post.get("num_comments", 0) or 0

            properties = {
                "分数": self._format_property_value("分数", new_score),
                "评论数": self._format_property_value("评论数", new_comments),
                "最后更新时间": self._format_property_value("最后更新时间", now),
                "处理状态": self._format_property_value("处理状态", "未处理"),
                "处理备注": self._format_property_value(
                    "处理备注",
                    f"增量热帖: 分数 {prev_score}→{new_score}, "
                    f"评论 {prev_comments}→{new_comments}"
                ),
            }

            # Remove None values
            properties = {k: v for k, v in properties.items() if v is not None}

            self.client.pages.update(page_id=page_id, properties=properties)
            self.logger.info(
                f"热帖更新: {post.get('id')} → {page_id} "
                f"(分数 {prev_score}→{new_score}, 评论 {prev_comments}→{new_comments})"
            )
            return True

        except Exception as e:
            self.logger.error(f"热帖更新失败 [{post.get('id')}]: {e}")
            return False

    # ==================================================================
    # KOL Sync: sync author dicts to Notion KOL database
    # ==================================================================

    def sync_kol_from_dict(self, author: dict, posts: list[dict] = None) -> Optional[str]:
        """Sync an author/KOL dict (from SQLite) to Notion KOL database.

        Returns the Notion page ID on success, None on failure.
        """
        if not notion_config.kol_database_id:
            self.logger.warning("NOTION_KOL_DATABASE_ID 未配置，跳过 KOL 同步")
            return None

        username = author.get("username", "")
        if not username:
            self.logger.error("Author dict missing 'username'")
            return None

        try:
            existing = self._find_kol_page(username)
            properties = self._build_kol_properties(author, posts)
            new_post_count = len(posts) if posts else 0

            if existing:
                page_id = existing["id"]
                self.client.pages.update(page_id=page_id, properties=properties)

                # Check if post list changed — if so, replace page content
                old_post_count = self._get_kol_post_count(existing)
                if new_post_count != old_post_count:
                    markdown = self._build_kol_markdown(author, posts)
                    if markdown:
                        self._replace_page_markdown(page_id, markdown)
                    self.logger.info(f"更新 KOL 页面 (含内容): {username} → {page_id}")
                else:
                    self.logger.info(f"更新 KOL 页面 (仅属性): {username} → {page_id}")
            else:
                response = self.client.pages.create(
                    parent={"database_id": notion_config.kol_database_id},
                    properties=properties,
                )
                page_id = response["id"]
                self.logger.info(f"创建 KOL 页面: {username} → {page_id}")

                markdown = self._build_kol_markdown(author, posts)
                if markdown:
                    self._write_page_markdown(page_id, markdown)

            return page_id

        except Exception as e:
            self.logger.error(f"sync_kol_from_dict 失败 [{username}]: {e}")
            return None

    def _get_kol_post_count(self, page: dict) -> int:
        """Extract post count from KOL page's 备注 field (heuristic)."""
        props = page.get("properties", {})
        notes = props.get("备注", {})
        rich_text = notes.get("rich_text", [])
        if rich_text:
            text = rich_text[0].get("plain_text", "")
            # Parse "本地帖子: N" from notes
            import re
            m = re.search(r"本地帖子:\s*(\d+)", text)
            if m:
                return int(m.group(1))
        return 0

    def _find_kol_page(self, username: str) -> Optional[Dict[str, Any]]:
        """Find existing KOL page by username (title column: KOL 名称)."""
        try:
            response = self.client.databases.query(
                database_id=notion_config.kol_database_id,
                filter={
                    "property": "KOL 名称",
                    "title": {"equals": username},
                },
                page_size=1,
            )
            results = response.get("results", [])
            return results[0] if results else None
        except Exception as e:
            self.logger.warning(f"查找 KOL 页面失败 [{username}]: {e}")
            return None

    def _build_kol_properties(self, author: dict, posts: list[dict] = None) -> Dict[str, Any]:
        """Build Notion properties for a KOL page.

        KOL DB schema:
          KOL 名称 (title), Comment Karma (number), Post Karma (number),
          Cake Day (date), 粉丝数量 (number), 主页 (email), Subreddit (multi_select),
          平台 (multi_select), 领域 (multi_select), 互动率 (number),
          Achivements (multi_select), 备注 (rich_text), 合作状态 (status),
          预算范围 (select), 最近合作日期 (date)
        """
        from datetime import datetime as _dt, timezone as _tz
        from collections import Counter

        username = author.get("username", "")
        link_karma = author.get("link_karma", 0)
        comment_karma = author.get("comment_karma", 0)
        total_karma = author.get("total_karma", 0)
        created_utc = author.get("created_utc", 0)
        kol_score = author.get("kol_score", 0)
        kol_tier = author.get("kol_tier", "watch")
        post_count = author.get("post_count", 0)
        avg_post_score = author.get("avg_post_score", 0)

        tier_cn = {
            "expert": "专家", "insider": "内行",
            "active": "活跃", "watch": "观察",
        }

        # Extract subreddit info from posts
        subreddit_counts = Counter()
        if posts:
            for p in posts:
                sub = p.get("subreddit", "")
                if sub:
                    subreddit_counts[sub] += 1

        # Map subreddits to domain tags
        domain_map = {
            "homenetworking": "家庭网络",
            "networking": "企业网络",
            "Ubiquiti": "网络设备",
            "TPLink_Omada": "Omada",
            "TplinkOmada": "Omada",
            "Omada_Networks": "Omada",
            "msp": "IT服务商",
        }
        domains = []
        for sub in subreddit_counts:
            tag = domain_map.get(sub)
            if tag and tag not in [d["name"] for d in domains]:
                domains.append({"name": tag})

        properties = {
            "KOL 名称": {
                "title": [{"text": {"content": username}}]
            },
            "Comment Karma": {"number": comment_karma},
            "Post Karma": {"number": link_karma},
            "粉丝数量": {"number": total_karma},
            "互动率": {"number": round(kol_score, 2)},
            "平台": {
                "multi_select": [{"name": "Reddit"}]
            },
            "主页": {"email": f"https://reddit.com/user/{username}"},
            "备注": {
                "rich_text": [{
                    "text": {
                        "content": (
                            f"KOL等级: {tier_cn.get(kol_tier, kol_tier)} "
                            f"(评分: {kol_score:.1f}/60) | "
                            f"本地帖子: {post_count} | "
                            f"平均分: {avg_post_score:.1f}"
                        )[:2000]
                    }
                }]
            },
        }

        # Subreddit (multi_select)
        if subreddit_counts:
            properties["Subreddit"] = {
                "multi_select": [{"name": sub} for sub in subreddit_counts]
            }

        # 领域 (multi_select)
        if domains:
            properties["领域"] = {"multi_select": domains}

        # Cake Day
        if created_utc:
            cake_day = _dt.fromtimestamp(created_utc, tz=_tz.utc)
            properties["Cake Day"] = {"date": {"start": cake_day.strftime("%Y-%m-%d")}}

        # Achievements
        achievements = []
        if author.get("is_gold"):
            achievements.append({"name": "Reddit Gold"})
        if author.get("is_mod"):
            achievements.append({"name": "Moderator"})
        if author.get("has_verified_email"):
            achievements.append({"name": "Verified Email"})
        if kol_tier == "expert":
            achievements.append({"name": "Expert"})
        elif kol_tier == "insider":
            achievements.append({"name": "Insider"})
        if achievements:
            properties["Achivements"] = {"multi_select": achievements}

        return properties

    def _build_kol_markdown(self, author: dict, posts: list[dict] = None) -> str:
        """Build markdown content for a KOL page."""
        lines = []
        username = author.get("username", "")

        lines.append("## 👤 用户概况")
        lines.append("")
        lines.append(f"**Reddit**: [u/{username}](https://www.reddit.com/user/{username})")
        lines.append("")

        total_karma = author.get("total_karma", 0)
        link_karma = author.get("link_karma", 0)
        comment_karma = author.get("comment_karma", 0)
        age_days = author.get("account_age_days", 0)
        age_years = age_days / 365 if age_days else 0

        lines.append(f"| 指标 | 值 |")
        lines.append(f"|---|---|")
        lines.append(f"| 总 Karma | {total_karma:,} |")
        lines.append(f"| 发帖 Karma | {link_karma:,} |")
        lines.append(f"| 评论 Karma | {comment_karma:,} |")
        lines.append(f"| 账号年龄 | {age_years:.1f} 年 ({age_days} 天) |")

        badges = []
        if author.get("is_gold"):
            badges.append("Reddit Gold")
        if author.get("is_mod"):
            badges.append("版主")
        if author.get("has_verified_email"):
            badges.append("邮箱已验证")
        if badges:
            lines.append(f"| 标签 | {', '.join(badges)} |")
        lines.append("")

        kol_score = author.get("kol_score", 0)
        kol_tier = author.get("kol_tier", "watch")
        tier_cn = {"expert": "专家", "insider": "内行", "active": "活跃", "watch": "观察"}
        lines.append("## 📊 KOL 评估")
        lines.append("")
        lines.append(f"**评分**: {kol_score:.1f} / 60  |  **等级**: {tier_cn.get(kol_tier, kol_tier)}")
        lines.append("")

        if posts:
            lines.append(f"## 📝 相关帖子 ({len(posts)} 篇)")
            lines.append("")
            for p in posts[:20]:
                title = p.get("title", "")
                score = p.get("score", 0)
                comments = p.get("num_comments", 0)
                subreddit = p.get("subreddit", "")
                permalink = p.get("permalink", "")
                ai_topic = p.get("ai_topic_category", "")

                link = f"https://www.reddit.com{permalink}" if permalink else ""
                topic_tag = f" [{ai_topic}]" if ai_topic and ai_topic != "not_relevant" else ""

                if link:
                    lines.append(f"- [{title}]({link}) — r/{subreddit} | ⬆️{score} 💬{comments}{topic_tag}")
                else:
                    lines.append(f"- {title} — r/{subreddit} | ⬆️{score} 💬{comments}{topic_tag}")
            lines.append("")

        return "\n".join(lines)

    # ==================================================================
    # YouTube Video Sync
    # ==================================================================

    def sync_youtube_video_from_dict(self, video: dict) -> Optional[str]:
        """Sync a YouTube video dict (from SQLite with comments) to Notion YouTube DB.

        Returns the Notion page ID on success, None on failure.
        """
        if not notion_config.youtube_database_id:
            self.logger.warning("NOTION_YOUTUBE_DATABASE_ID 未配置，跳过 YouTube 同步")
            return None

        video_id = video.get("id", "")
        if not video_id:
            self.logger.error("Video dict missing 'id'")
            return None

        try:
            existing = self._find_existing_youtube_page(video_id)
            properties = self._build_youtube_properties(video)

            if existing:
                page_id = existing["id"]
                self.client.pages.update(page_id=page_id, properties=properties)

                old_comments = self._get_yt_page_comment_count(existing)
                new_comments = len(video.get("comments", []))
                if new_comments != old_comments:
                    markdown = self._build_youtube_page_content(video)
                    if markdown:
                        self._replace_page_markdown(page_id, markdown)
                    self.logger.info(f"更新 YouTube 页面 (含内容): {page_id}")
                else:
                    self.logger.info(f"更新 YouTube 页面 (仅属性): {page_id}")
            else:
                response = self.client.pages.create(
                    parent={"database_id": notion_config.youtube_database_id},
                    properties=properties,
                )
                page_id = response["id"]
                self.logger.info(f"创建 YouTube 页面: {page_id}")

                markdown = self._build_youtube_page_content(video)
                if markdown:
                    self._write_page_markdown(page_id, markdown)

            return page_id

        except Exception as e:
            self.logger.error(f"sync_youtube_video_from_dict 失败 [{video_id}]: {e}")
            return None

    def _find_existing_youtube_page(self, video_id: str) -> Optional[Dict[str, Any]]:
        """查找是否已存在相同 Video ID 的页面"""
        try:
            response = self.client.databases.query(
                database_id=notion_config.youtube_database_id,
                filter={
                    "property": "Video ID",
                    "rich_text": {"equals": video_id},
                },
                page_size=1,
            )
            results = response.get("results", [])
            return results[0] if results else None
        except Exception as e:
            self.logger.warning(f"查找 YouTube 页面失败: {e}")
            return None

    def _get_yt_page_comment_count(self, page: dict) -> int:
        """Extract comment count from an existing YouTube Notion page."""
        props = page.get("properties", {})
        num_prop = props.get("评论数", {})
        return num_prop.get("number", 0) or 0

    def _build_youtube_properties(self, video: dict) -> Dict[str, Any]:
        """Build Notion properties for a YouTube video page."""
        from datetime import datetime as _dt, timezone as _tz

        now = _dt.now(_tz.utc)
        week_str = now.strftime("%G-W%V")

        sentiment_map = {
            "positive": "正面", "negative": "负面",
            "neutral": "中性", "mixed": "混合",
        }
        topic_map = {
            "product_issue": "技术问题", "feature_request": "功能需求",
            "deployment": "部署案例", "comparison": "竞品对比",
            "recommendation_ask": "产品推荐", "firmware_update": "固件更新",
            "general_discussion": "一般讨论", "competitor_intel": "竞品情报",
            "positive_feedback": "正面反馈", "negative_feedback": "负面反馈",
            "not_relevant": "低相关",
        }

        ai_sentiment = video.get("ai_sentiment_quick", "neutral")
        ai_topic = video.get("ai_topic_category", "")
        ai_relevance = video.get("ai_relevance_score", 0.0) or 0.0

        sentiment_score_map = {
            "positive": 0.6, "negative": -0.6,
            "neutral": 0.0, "mixed": 0.0,
        }

        discovered_map = {
            "search": "关键词搜索",
            "channel_monitor": "频道监控",
        }

        property_mappings = {
            "标题": video.get("title", ""),
            "描述": (video.get("description", "") or "")[:500],
            "来源": "YouTube",
            "类型": "Video",
            "Video ID": video["id"],
            "频道名": video.get("channel_title", ""),
            "频道 ID": video.get("channel_id", ""),
            "播放量": video.get("view_count", 0),
            "点赞数": video.get("like_count", 0),
            "评论数": video.get("comment_count", 0),
            "时长": video.get("duration", ""),
            "发布时间": video.get("published_at", ""),
            "采集时间": now,
            "最后更新时间": now,
            "视频链接": video.get("url", f"https://www.youtube.com/watch?v={video['id']}"),
            "缩略图": video.get("thumbnail_url", ""),
            "相关性得分": ai_relevance,
            "周报周期": week_str,
            "情感倾向": sentiment_map.get(ai_sentiment, "中性"),
            "情感分数_数值": sentiment_score_map.get(ai_sentiment, 0.0),
            "AI摘要": video.get("ai_brief_reason", ""),
            "发现来源": discovered_map.get(video.get("discovered_via", "search"), "关键词搜索"),
            "处理状态": "未处理",
        }

        if ai_topic and ai_topic != "not_relevant":
            property_mappings["主题分类"] = topic_map.get(ai_topic, ai_topic)

        # Alert level (YouTube thresholds are higher than Reddit)
        view_count = video.get("view_count", 0) or 0
        comment_count = video.get("comment_count", 0) or 0
        alert_level = "none"
        if ai_sentiment == "negative" and (view_count > 10000 or comment_count > 50):
            alert_level = "critical"
        elif ai_sentiment == "negative" and (view_count > 1000 or comment_count > 20):
            alert_level = "high"
        elif ai_sentiment == "negative":
            alert_level = "medium"
        property_mappings["预警等级"] = alert_level

        # Priority
        priority = "低"
        if ai_relevance >= 0.8 and (view_count > 5000 or comment_count > 30):
            priority = "高"
        elif ai_relevance >= 0.5:
            priority = "中"
        property_mappings["优先级"] = priority

        # Temporarily switch schema cache to YouTube DB
        old_schema = self._database_schema
        self._database_schema = None
        old_db_id = self.database_id

        try:
            self.database_id = notion_config.youtube_database_id
            properties = {}
            for prop_name, value in property_mappings.items():
                formatted = self._format_property_value(prop_name, value)
                if formatted is not None:
                    properties[prop_name] = formatted
        finally:
            self._database_schema = old_schema
            self.database_id = old_db_id

        return properties

    def _build_youtube_page_content(self, video: dict) -> str:
        """Build markdown content for a YouTube video page."""
        lines = []

        lines.append("## 📺 视频信息")
        lines.append("")
        lines.append(f"频道: [{video.get('channel_title', '')}](https://www.youtube.com/channel/{video.get('channel_id', '')})")
        lines.append("")

        published = video.get("published_at", "")
        if published:
            lines.append(f"发布时间: {published[:19].replace('T', ' ')} UTC")
        lines.append("")

        view_count = video.get("view_count", 0)
        like_count = video.get("like_count", 0)
        comment_count = video.get("comment_count", 0)
        duration = video.get("duration", "")
        lines.append(f"播放量: {view_count:,} | 点赞: {like_count:,} | 评论: {comment_count:,} | 时长: {duration}")
        lines.append("")

        ai_reason = video.get("ai_brief_reason", "")
        ai_topic = video.get("ai_topic_category", "")
        ai_sentiment = video.get("ai_sentiment_quick", "")
        ai_relevance = video.get("ai_relevance_score", 0)
        if ai_reason:
            lines.append(f"**AI 初筛**: {ai_reason} (相关性: {ai_relevance:.2f}, 话题: {ai_topic}, 情感: {ai_sentiment})")
            lines.append("")

        lines.append("## 📝 视频描述")
        lines.append("")
        description = video.get("description", "") or ""
        if description.strip():
            lines.append(description.strip())
        else:
            lines.append("（无描述）")
        lines.append("")

        comments = video.get("comments", [])
        if comments:
            lines.append(f"## 💬 评论 ({len(comments)} 条)")
            lines.append("")
            for c in comments:
                author = c.get("author", "")
                like_c = c.get("like_count", 0)
                text = (c.get("text", "") or "").strip()
                is_reply = c.get("is_reply", False)
                indent = "\t" if is_reply else ""

                lines.append(f"{indent}<details>")
                lines.append(f"{indent}<summary>💬 {author} (👍 {like_c})</summary>")
                lines.append("")
                if text:
                    for bline in text.split("\n"):
                        lines.append(f"{indent}\t{bline}")
                else:
                    lines.append(f"{indent}\t（空评论）")
                lines.append("")
                lines.append(f"{indent}</details>")
                lines.append("")

        return "\n".join(lines)

    def update_hot_youtube_video(self, video: dict) -> bool:
        """Update a hot video's Notion page: refresh stats and reset 处理状态."""
        page_id = video.get("notion_page_id")
        if not page_id:
            self.logger.warning(f"Hot video {video.get('id')} has no notion_page_id")
            return False

        try:
            from datetime import datetime as _dt, timezone as _tz
            now = _dt.now(_tz.utc)

            prev_views = video.get("prev_view_count", 0) or 0
            prev_likes = video.get("prev_like_count", 0) or 0
            prev_comments = video.get("prev_comment_count", 0) or 0
            new_views = video.get("view_count", 0) or 0
            new_likes = video.get("like_count", 0) or 0
            new_comments = video.get("comment_count", 0) or 0

            old_schema = self._database_schema
            self._database_schema = None
            old_db_id = self.database_id

            try:
                self.database_id = notion_config.youtube_database_id
                properties = {
                    "播放量": self._format_property_value("播放量", new_views),
                    "点赞数": self._format_property_value("点赞数", new_likes),
                    "评论数": self._format_property_value("评论数", new_comments),
                    "最后更新时间": self._format_property_value("最后更新时间", now),
                    "处理状态": self._format_property_value("处理状态", "未处理"),
                    "处理备注": self._format_property_value(
                        "处理备注",
                        f"热视频: 播放 {prev_views:,}→{new_views:,}, "
                        f"点赞 {prev_likes}→{new_likes}, "
                        f"评论 {prev_comments}→{new_comments}"
                    ),
                }
            finally:
                self._database_schema = old_schema
                self.database_id = old_db_id

            properties = {k: v for k, v in properties.items() if v is not None}

            self.client.pages.update(page_id=page_id, properties=properties)
            self.logger.info(
                f"热视频更新: {video.get('id')} → {page_id} "
                f"(播放 {prev_views:,}→{new_views:,})"
            )
            return True

        except Exception as e:
            self.logger.error(f"热视频更新失败 [{video.get('id')}]: {e}")
            return False

    # ==================================================================
    # YouTube KOL Sync (channels → KOL database)
    # ==================================================================

    def sync_youtube_kol_from_dict(self, channel: dict, videos: list[dict] = None) -> Optional[str]:
        """Sync a YouTube channel to Notion KOL database.

        Returns the Notion page ID on success, None on failure.
        """
        if not notion_config.kol_database_id:
            self.logger.warning("NOTION_KOL_DATABASE_ID 未配置，跳过 YouTube KOL 同步")
            return None

        channel_title = channel.get("title", "")
        if not channel_title:
            return None

        try:
            existing = self._find_kol_page(channel_title)
            properties = self._build_youtube_kol_properties(channel, videos)

            if existing:
                page_id = existing["id"]
                self.client.pages.update(page_id=page_id, properties=properties)
                self.logger.info(f"更新 YouTube KOL 页面: {channel_title} → {page_id}")
            else:
                response = self.client.pages.create(
                    parent={"database_id": notion_config.kol_database_id},
                    properties=properties,
                )
                page_id = response["id"]
                self.logger.info(f"创建 YouTube KOL 页面: {channel_title} → {page_id}")

                markdown = self._build_youtube_kol_markdown(channel, videos)
                if markdown:
                    self._write_page_markdown(page_id, markdown)

            return page_id

        except Exception as e:
            self.logger.error(f"sync_youtube_kol_from_dict 失败 [{channel_title}]: {e}")
            return None

    def _build_youtube_kol_properties(self, channel: dict, videos: list[dict] = None) -> Dict[str, Any]:
        """Build Notion properties for a YouTube KOL page."""
        channel_title = channel.get("title", "")
        subscriber_count = channel.get("subscriber_count", 0)
        video_count = channel.get("video_count", 0)
        total_views = channel.get("view_count", 0)
        kol_score = channel.get("kol_score", 0)
        kol_tier = channel.get("kol_tier", "watch")

        tier_cn = {
            "expert": "专家", "insider": "内行",
            "active": "活跃", "watch": "观察",
        }

        properties = {
            "KOL 名称": {
                "title": [{"text": {"content": channel_title}}]
            },
            "粉丝数量": {"number": subscriber_count},
            "互动率": {"number": round(kol_score, 2)},
            "平台": {
                "multi_select": [{"name": "YouTube"}]
            },
            "主页": {"email": f"https://www.youtube.com/channel/{channel.get('id', '')}"},
            "备注": {
                "rich_text": [{
                    "text": {
                        "content": (
                            f"KOL等级: {tier_cn.get(kol_tier, kol_tier)} "
                            f"(评分: {kol_score:.1f}) | "
                            f"订阅: {subscriber_count:,} | "
                            f"视频: {video_count} | "
                            f"总播放: {total_views:,}"
                        )[:2000]
                    }
                }]
            },
            "领域": {"multi_select": [{"name": "网络设备"}]},
        }

        return properties

    def _build_youtube_kol_markdown(self, channel: dict, videos: list[dict] = None) -> str:
        """Build markdown content for a YouTube KOL page."""
        lines = []
        title = channel.get("title", "")
        channel_id = channel.get("id", "")

        lines.append("## 📺 频道概况")
        lines.append("")
        lines.append(f"**YouTube**: [{title}](https://www.youtube.com/channel/{channel_id})")
        lines.append("")

        lines.append("| 指标 | 值 |")
        lines.append("|---|---|")
        lines.append(f"| 订阅数 | {channel.get('subscriber_count', 0):,} |")
        lines.append(f"| 视频数 | {channel.get('video_count', 0):,} |")
        lines.append(f"| 总播放量 | {channel.get('view_count', 0):,} |")
        lines.append("")

        kol_score = channel.get("kol_score", 0)
        kol_tier = channel.get("kol_tier", "watch")
        tier_cn = {"expert": "专家", "insider": "内行", "active": "活跃", "watch": "观察"}
        lines.append("## 📊 KOL 评估")
        lines.append("")
        lines.append(f"**评分**: {kol_score:.1f}  |  **等级**: {tier_cn.get(kol_tier, kol_tier)}")
        lines.append("")

        if videos:
            lines.append(f"## 📝 相关视频 ({len(videos)} 个)")
            lines.append("")
            for v in videos[:20]:
                vtitle = v.get("title", "")
                views = v.get("view_count", 0)
                likes = v.get("like_count", 0)
                vid = v.get("id", "")
                link = f"https://www.youtube.com/watch?v={vid}"
                lines.append(f"- [{vtitle}]({link}) | 👁️{views:,} 👍{likes:,}")
            lines.append("")

        return "\n".join(lines)
