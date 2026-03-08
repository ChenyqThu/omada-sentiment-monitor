"""
Weekly Voice Report Generator
Queries Notion database for a given week's data, aggregates statistics,
and creates a Notion page with the Weekly Voice Report (Omada Pulse).
"""
import os
import sys
import requests
from datetime import datetime, timedelta, timezone
from collections import Counter, defaultdict
from typing import Optional

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import notion_config
from src.utils.logger import LoggerMixin

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_API_VERSION = "2022-06-28"
REPORT_DATABASE_ID = "31d15375830d80a483a8e4b6c43e3bfb"

# 情感标签映射（中文 -> 标准键）
SENTIMENT_LABEL_MAP = {
    "正面": "positive",
    "负面": "negative",
    "中性": "neutral",
    "混合": "mixed",
    "positive": "positive",
    "negative": "negative",
    "neutral": "neutral",
    "mixed": "mixed",
}

# 情感分数字符串解析（Select 字段回退）
SENTIMENT_SCORE_PARSE = {
    "正面": 0.7,
    "negative": -0.7,
    "负面": -0.7,
    "中性": 0.0,
    "neutral": 0.0,
    "混合": 0.0,
    "mixed": 0.0,
    "positive": 0.7,
}


def _isoweek_to_dates(week_str: str):
    """Convert ISO week string '2026-W10' to (start_date, end_date) datetimes (UTC, Monday–Sunday)."""
    year, week = week_str.split("-W")
    year, week = int(year), int(week)
    # ISO week Monday
    start = datetime.fromisocalendar(year, week, 1).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=timezone.utc
    )
    end = start + timedelta(days=7)
    return start, end


def _previous_week(week_str: str) -> str:
    """Return the ISO week string for the week before the given one."""
    start, _ = _isoweek_to_dates(week_str)
    prev_start = start - timedelta(days=7)
    return prev_start.strftime("%G-W%V")


def _current_iso_week() -> str:
    """Return the previous ISO week string relative to today."""
    today = datetime.now(timezone.utc)
    # Use last week
    last_week_day = today - timedelta(days=7)
    return last_week_day.strftime("%G-W%V")


def _safe_get_property(properties: dict, key: str, prop_type: str, default=None):
    """Safely extract a typed value from a Notion property dict."""
    prop = properties.get(key)
    if not prop:
        return default
    try:
        if prop_type == "title":
            items = prop.get("title", [])
            return "".join(t.get("plain_text", "") for t in items) if items else default
        elif prop_type == "rich_text":
            items = prop.get("rich_text", [])
            return "".join(t.get("plain_text", "") for t in items) if items else default
        elif prop_type == "number":
            return prop.get("number", default)
        elif prop_type == "select":
            sel = prop.get("select")
            return sel.get("name") if sel else default
        elif prop_type == "multi_select":
            return [s.get("name", "") for s in prop.get("multi_select", [])]
        elif prop_type == "date":
            date_obj = prop.get("date")
            return date_obj.get("start") if date_obj else default
        elif prop_type == "url":
            return prop.get("url", default)
        elif prop_type == "checkbox":
            return prop.get("checkbox", default)
        else:
            return default
    except Exception:
        return default


def _txt_block(content: str) -> dict:
    """Build a Notion paragraph block."""
    return {
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
        },
    }


def _heading2_block(content: str) -> dict:
    return {
        "type": "heading_2",
        "heading_2": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
        },
    }


def _bullet_block(content: str) -> dict:
    return {
        "type": "bulleted_list_item",
        "bulleted_list_item": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}]
        },
    }


def _divider_block() -> dict:
    return {"type": "divider", "divider": {}}


def _callout_block(content: str, emoji: str = "💡") -> dict:
    return {
        "type": "callout",
        "callout": {
            "rich_text": [{"type": "text", "text": {"content": content[:2000]}}],
            "icon": {"type": "emoji", "emoji": emoji},
        },
    }


class WeeklyReportGenerator(LoggerMixin):
    """Generates Weekly Voice Report from Notion database data."""

    DATABASE_ID = "21d15375830d803aa102cec9b46957da"

    def __init__(
        self,
        notion_token: str,
        database_id: str,
        report_parent_page_id: str = None,
    ):
        """
        Args:
            notion_token: Notion API token
            database_id: Source database ID
            report_parent_page_id: Parent page ID where reports are created (optional)
        """
        super().__init__()
        if not notion_token:
            raise ValueError("Notion token is required")
        self.notion_token = notion_token
        self.database_id = database_id
        self.report_parent_page_id = report_parent_page_id
        self._headers = {
            "Authorization": f"Bearer {self.notion_token}",
            "Notion-Version": NOTION_API_VERSION,
            "Content-Type": "application/json",
        }
        self.logger.info(
            f"WeeklyReportGenerator initialized. Database: {self.database_id[:8]}..."
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_report(self, week: str = None) -> str:
        """Main entry point. Generate report for given week (ISO format '2026-W10').
        If week is None, use the previous week.
        Returns the created page URL.
        """
        if week is None:
            week = _current_iso_week()

        self.logger.info(f"生成周报: {week}")

        start_date, end_date = _isoweek_to_dates(week)
        self.logger.info(
            f"查询日期范围: {start_date.date()} ~ {(end_date - timedelta(seconds=1)).date()}"
        )

        # Query current week data
        records = self._query_week_data(start_date, end_date)
        self.logger.info(f"本周记录数: {len(records)}")

        # Aggregate stats
        stats = self._aggregate_stats(records)

        # Get previous week stats for trend comparison
        prev_week_str = _previous_week(week)
        prev_stats = self._get_previous_week_stats(start_date)

        # Compute trends
        trends = self._compute_trends(stats, prev_stats)

        # Save stats/trends for use in _create_report_page
        self._last_stats = stats
        self._last_trends = trends

        # Build content blocks
        content_blocks = self._build_report_content(week, stats, trends)

        # Create Notion page
        page_url = self._create_report_page(week, content_blocks)
        self.logger.info(f"周报页面创建成功: {page_url}")
        return page_url

    # ------------------------------------------------------------------
    # Data querying
    # ------------------------------------------------------------------

    def _query_week_data(self, start_date: datetime, end_date: datetime) -> list[dict]:
        """Query all records from the database within the date range.
        Uses the '采集时间' (Collected) date field for filtering.
        Handles pagination.
        """
        records = []
        start_cursor = None

        filter_payload = {
            "and": [
                {
                    "property": "采集时间",
                    "date": {"on_or_after": start_date.isoformat()},
                },
                {
                    "property": "采集时间",
                    "date": {"before": end_date.isoformat()},
                },
            ]
        }

        page_num = 0
        while True:
            page_num += 1
            body: dict = {
                "filter": filter_payload,
                "page_size": 100,
            }
            if start_cursor:
                body["start_cursor"] = start_cursor

            try:
                resp = requests.post(
                    f"{NOTION_API_BASE}/databases/{self.database_id}/query",
                    headers=self._headers,
                    json=body,
                    timeout=30,
                )
                resp.raise_for_status()
                data = resp.json()
            except requests.RequestException as e:
                self.logger.error(f"查询 Notion 数据库失败 (第{page_num}页): {e}")
                break

            page_results = data.get("results", [])
            records.extend(page_results)
            self.logger.debug(f"第{page_num}页: 获取 {len(page_results)} 条记录")

            if data.get("has_more") and data.get("next_cursor"):
                start_cursor = data["next_cursor"]
            else:
                break

        return records

    # ------------------------------------------------------------------
    # Aggregation
    # ------------------------------------------------------------------

    def _aggregate_stats(self, records: list[dict]) -> dict:
        """Compute aggregated statistics from a list of Notion page records."""
        total_mentions = len(records)

        sentiment_distribution = {"positive": 0, "negative": 0, "neutral": 0, "mixed": 0}
        sentiment_scores = []
        subreddit_counter: Counter = Counter()
        topic_counter: Counter = Counter()
        keyword_counter: Counter = Counter()
        competitor_counter: Counter = Counter()
        opportunity_posts = []
        kol_posts = []
        high_influence_posts = []
        total_engagement = 0

        for record in records:
            props = record.get("properties", {})

            # --- Sentiment ---
            sentiment_label = _safe_get_property(props, "情感倾向", "select") or ""
            sentiment_key = SENTIMENT_LABEL_MAP.get(sentiment_label, "neutral")
            if sentiment_key in sentiment_distribution:
                sentiment_distribution[sentiment_key] += 1
            else:
                sentiment_distribution["neutral"] += 1

            # Sentiment score: try numeric field first, fall back to select label
            score_num = _safe_get_property(props, "情感分数_数值", "number")
            if score_num is not None:
                sentiment_scores.append(float(score_num))
            else:
                score_str = _safe_get_property(props, "情感分数", "select") or sentiment_label
                fallback_score = SENTIMENT_SCORE_PARSE.get(score_str, 0.0)
                if fallback_score != 0.0 or score_str:
                    sentiment_scores.append(fallback_score)

            # --- Subreddit ---
            subreddit = _safe_get_property(props, "Subreddit", "rich_text") or \
                        _safe_get_property(props, "Subreddit", "select") or ""
            if subreddit:
                subreddit_counter[subreddit] += 1

            # --- Topics ---
            topics = _safe_get_property(props, "主题分类", "multi_select") or []
            for t in topics:
                if t:
                    topic_counter[t] += 1

            # --- Keywords ---
            keywords = _safe_get_property(props, "关键词", "multi_select") or \
                       _safe_get_property(props, "匹配关键词", "multi_select") or []
            for kw in keywords:
                if kw:
                    keyword_counter[kw] += 1

            # --- Engagement ---
            score_val = _safe_get_property(props, "分数", "number") or 0
            comments_val = _safe_get_property(props, "评论数", "number") or 0
            try:
                total_engagement += int(score_val) + int(comments_val)
            except (TypeError, ValueError):
                pass

            # --- Influence score ---
            influence = _safe_get_property(props, "影响力评分", "number") or 0

            # Build a lightweight summary dict for post references
            page_id = record.get("id", "")
            title = _safe_get_property(props, "标题", "title") or "(无标题)"
            reddit_link = _safe_get_property(props, "Reddit链接", "url") or ""
            author = _safe_get_property(props, "作者", "rich_text") or ""
            kol_score = _safe_get_property(props, "KOL评分", "number") or \
                        _safe_get_property(props, "用户Karma", "number") or 0

            post_summary = {
                "id": page_id,
                "title": title,
                "reddit_link": reddit_link,
                "author": author,
                "influence": influence,
                "score": score_val,
                "comments": comments_val,
                "sentiment": sentiment_key,
                "subreddit": subreddit,
                "kol_score": kol_score,
            }

            # High influence posts (collect all, sort later)
            high_influence_posts.append(post_summary)

            # Opportunity posts — 机会类型 set (multi_select or select)
            opportunity_type = _safe_get_property(props, "机会类型", "select") or \
                               _safe_get_property(props, "机会类型", "rich_text") or ""
            opportunity_types = _safe_get_property(props, "机会类型", "multi_select") or []
            if opportunity_type or opportunity_types:
                opp_label = opportunity_type or ", ".join(opportunity_types)
                opportunity_posts.append({**post_summary, "opportunity_type": opp_label})

            # KOL activity — posts by high-karma / KOL authors
            if kol_score and float(kol_score) >= 10000:
                kol_posts.append(post_summary)

            # Competitor mentions
            competitor_mention = _safe_get_property(props, "竞品提及", "multi_select") or \
                                 _safe_get_property(props, "竞品", "multi_select") or []
            for comp in competitor_mention:
                if comp:
                    competitor_counter[comp] += 1

        # Sort and trim high influence posts
        high_influence_posts.sort(key=lambda p: float(p.get("influence", 0) or 0), reverse=True)
        high_influence_posts = high_influence_posts[:10]

        avg_sentiment_score = (
            sum(sentiment_scores) / len(sentiment_scores) if sentiment_scores else 0.0
        )

        return {
            "total_mentions": total_mentions,
            "sentiment_distribution": sentiment_distribution,
            "avg_sentiment_score": round(avg_sentiment_score, 3),
            "top_subreddits": subreddit_counter.most_common(10),
            "top_topics": topic_counter.most_common(5),
            "top_keywords": keyword_counter.most_common(10),
            "high_influence_posts": high_influence_posts,
            "competitor_mentions": dict(competitor_counter),
            "opportunity_posts": opportunity_posts[:10],
            "kol_activity": kol_posts[:10],
            "total_engagement": total_engagement,
        }

    # ------------------------------------------------------------------
    # Trend computation
    # ------------------------------------------------------------------

    def _compute_trends(self, current_stats: dict, prev_week_stats: dict = None) -> dict:
        """Compare with previous week to identify trends.
        Returns mention_trend, sentiment_trend, engagement_trend.
        """
        if not prev_week_stats or prev_week_stats.get("total_mentions", 0) == 0:
            return {
                "mention_trend": "flat",
                "mention_delta": 0,
                "sentiment_trend": "flat",
                "sentiment_delta": 0.0,
                "engagement_trend": "flat",
                "engagement_delta": 0,
            }

        # Mention trend
        cur_mentions = current_stats.get("total_mentions", 0)
        prev_mentions = prev_week_stats.get("total_mentions", 0)
        mention_delta = cur_mentions - prev_mentions
        if mention_delta > 0:
            mention_trend = "up"
        elif mention_delta < 0:
            mention_trend = "down"
        else:
            mention_trend = "flat"

        # Sentiment trend
        cur_sentiment = current_stats.get("avg_sentiment_score", 0.0)
        prev_sentiment = prev_week_stats.get("avg_sentiment_score", 0.0)
        sentiment_delta = round(cur_sentiment - prev_sentiment, 3)
        if sentiment_delta > 0.05:
            sentiment_trend = "up"
        elif sentiment_delta < -0.05:
            sentiment_trend = "down"
        else:
            sentiment_trend = "flat"

        # Engagement trend
        cur_engagement = current_stats.get("total_engagement", 0)
        prev_engagement = prev_week_stats.get("total_engagement", 0)
        engagement_delta = cur_engagement - prev_engagement
        if engagement_delta > 0:
            engagement_trend = "up"
        elif engagement_delta < 0:
            engagement_trend = "down"
        else:
            engagement_trend = "flat"

        return {
            "mention_trend": mention_trend,
            "mention_delta": mention_delta,
            "sentiment_trend": sentiment_trend,
            "sentiment_delta": sentiment_delta,
            "engagement_trend": engagement_trend,
            "engagement_delta": engagement_delta,
        }

    # ------------------------------------------------------------------
    # Report content builder
    # ------------------------------------------------------------------

    def _build_report_content(self, week: str, stats: dict, trends: dict) -> list[dict]:
        """Build Notion page content blocks for the report.

        Report structure (per Omada Pulse spec):
        1. 本周概览 — Key metrics with trend arrows (↑↓→)
        2. 热门话题 Top 5 — Most discussed topics with context
        3. 情绪趋势 — Sentiment distribution chart description, notable shifts
        4. 高价值机会 — Posts worth engaging (include Reddit links)
        5. KOL 动态 — Notable user activities
        6. 竞品情报 — Competitor mention analysis
        7. 行动建议 — Top 3 recommended actions
        """
        blocks = []

        total = stats.get("total_mentions", 0)
        if total == 0:
            blocks.append(
                _callout_block(
                    f"本周 ({week}) 暂无数据收录，请检查采集任务是否正常运行。", "⚠️"
                )
            )
            return blocks

        trend_arrow = {"up": "↑", "down": "↓", "flat": "→"}

        # ----------------------------------------------------------------
        # 1. 本周概览
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("一、本周概览"))

        mention_arrow = trend_arrow[trends.get("mention_trend", "flat")]
        engagement_arrow = trend_arrow[trends.get("engagement_trend", "flat")]
        sentiment_arrow = trend_arrow[trends.get("sentiment_trend", "flat")]
        mention_delta = trends.get("mention_delta", 0)
        engagement_delta = trends.get("engagement_delta", 0)
        sentiment_delta = trends.get("sentiment_delta", 0.0)

        blocks.append(
            _bullet_block(
                f"总提及量：{total} 条  {mention_arrow}  "
                f"(较上周 {'+' if mention_delta >= 0 else ''}{mention_delta} 条)"
            )
        )
        blocks.append(
            _bullet_block(
                f"总互动量（分数+评论）：{stats.get('total_engagement', 0)}  {engagement_arrow}  "
                f"(较上周 {'+' if engagement_delta >= 0 else ''}{engagement_delta})"
            )
        )
        avg_score = stats.get("avg_sentiment_score", 0.0)
        blocks.append(
            _bullet_block(
                f"平均情感分数：{avg_score:+.3f}  {sentiment_arrow}  "
                f"(较上周 {'+' if sentiment_delta >= 0 else ''}{sentiment_delta:.3f})"
            )
        )

        # Top subreddits summary
        top_subs = stats.get("top_subreddits", [])
        if top_subs:
            subs_str = "、".join(f"{s}({c}条)" for s, c in top_subs[:5])
            blocks.append(_bullet_block(f"活跃社区：{subs_str}"))

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 2. 热门话题 Top 5
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("二、热门话题 Top 5"))

        top_topics = stats.get("top_topics", [])
        if top_topics:
            for rank, (topic, count) in enumerate(top_topics[:5], start=1):
                blocks.append(_bullet_block(f"{rank}. {topic}（{count} 条讨论）"))
        else:
            blocks.append(_txt_block("本周暂无主题分类数据。"))

        # Top keywords as supplementary context
        top_kws = stats.get("top_keywords", [])
        if top_kws:
            kws_str = "、".join(f"{kw}({c})" for kw, c in top_kws[:8])
            blocks.append(_txt_block(f"高频关键词：{kws_str}"))

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 3. 情绪趋势
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("三、情绪趋势"))

        dist = stats.get("sentiment_distribution", {})
        pos = dist.get("positive", 0)
        neg = dist.get("negative", 0)
        neu = dist.get("neutral", 0)
        mix = dist.get("mixed", 0)
        total_with_sentiment = pos + neg + neu + mix or 1  # avoid div/0

        def pct(n):
            return f"{n / total_with_sentiment * 100:.1f}%"

        blocks.append(
            _txt_block(
                f"情感分布：正面 {pos} 条（{pct(pos)}）｜负面 {neg} 条（{pct(neg)}）｜"
                f"中性 {neu} 条（{pct(neu)}）｜混合 {mix} 条（{pct(mix)}）"
            )
        )
        blocks.append(_txt_block(f"本周平均情感分数：{avg_score:+.3f}（区间 -1.0 ~ +1.0）"))

        # Notable shift callout
        neg_pct = neg / total_with_sentiment
        if neg_pct >= 0.4:
            blocks.append(
                _callout_block(
                    f"本周负面声量占比较高（{pct(neg)}），建议优先关注负面帖子并及时响应。", "🚨"
                )
            )
        elif pos / total_with_sentiment >= 0.5:
            blocks.append(
                _callout_block(
                    f"本周正面声量占比良好（{pct(pos)}），可适时扩大积极互动。", "✅"
                )
            )

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 4. 高价值机会
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("四、高价值机会"))

        opp_posts = stats.get("opportunity_posts", [])
        if opp_posts:
            for post in opp_posts[:5]:
                link = post.get("reddit_link", "")
                link_text = f" | {link}" if link else ""
                blocks.append(
                    _bullet_block(
                        f"[{post.get('opportunity_type', '机会')}] {post.get('title', '')} "
                        f"(作者: {post.get('author', '')}, 影响力: {post.get('influence', 0)})"
                        f"{link_text}"
                    )
                )
        else:
            # Fall back to high influence posts when no opportunity_type tagged
            high_posts = stats.get("high_influence_posts", [])
            if high_posts:
                blocks.append(_txt_block("（本周暂无标记机会类型，以下为高影响力帖子，供参考）"))
                for post in high_posts[:5]:
                    link = post.get("reddit_link", "")
                    link_text = f" | {link}" if link else ""
                    blocks.append(
                        _bullet_block(
                            f"{post.get('title', '')} "
                            f"(作者: {post.get('author', '')}, 影响力: {post.get('influence', 0)}, "
                            f"互动: {int(post.get('score', 0))}分/{int(post.get('comments', 0))}评论)"
                            f"{link_text}"
                        )
                    )
            else:
                blocks.append(_txt_block("本周暂无高价值机会帖子。"))

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 5. KOL 动态
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("五、KOL 动态"))

        kol_posts = stats.get("kol_activity", [])
        if kol_posts:
            for post in kol_posts[:5]:
                link = post.get("reddit_link", "")
                link_text = f" | {link}" if link else ""
                blocks.append(
                    _bullet_block(
                        f"{post.get('author', '')}（Karma: {int(post.get('kol_score', 0)):,}）发布：{post.get('title', '')}"
                        f"{link_text}"
                    )
                )
        else:
            blocks.append(_txt_block("本周暂无高 Karma 用户（KOL）活动记录。"))

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 6. 竞品情报
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("六、竞品情报"))

        competitor_mentions = stats.get("competitor_mentions", {})
        if competitor_mentions:
            sorted_comps = sorted(competitor_mentions.items(), key=lambda x: x[1], reverse=True)
            for comp, count in sorted_comps[:8]:
                blocks.append(_bullet_block(f"{comp}：{count} 条提及"))
        else:
            blocks.append(_txt_block('本周暂无竞品提及数据（字段"竞品提及"尚未采集）。'))

        blocks.append(_divider_block())

        # ----------------------------------------------------------------
        # 7. 行动建议
        # ----------------------------------------------------------------
        blocks.append(_heading2_block("七、行动建议"))

        # Generate top 3 recommendations based on data
        recommendations = self._generate_recommendations(stats, trends)
        for i, rec in enumerate(recommendations[:3], start=1):
            blocks.append(_bullet_block(f"{i}. {rec}"))

        return blocks

    def _generate_recommendations(self, stats: dict, trends: dict) -> list[str]:
        """Derive action recommendations from aggregated stats and trends."""
        recs = []

        dist = stats.get("sentiment_distribution", {})
        neg = dist.get("negative", 0)
        total = stats.get("total_mentions", 1) or 1
        neg_pct = neg / total

        if neg_pct >= 0.3:
            recs.append(
                f"负面声量占比 {neg_pct * 100:.0f}%，建议本周内优先回复并介入高影响力负面帖子，"
                "降低潜在舆情风险。"
            )

        opp_posts = stats.get("opportunity_posts", [])
        if opp_posts:
            recs.append(
                f"共发现 {len(opp_posts)} 个高价值机会帖，建议市场团队在 48 小时内跟进，"
                "提供官方解答或产品推荐。"
            )

        top_topics = stats.get("top_topics", [])
        if top_topics:
            top_topic = top_topics[0][0]
            recs.append(
                f"热门话题「{top_topic}」讨论最为活跃，可考虑针对该话题制作内容或 FAQ，"
                "提升社区品牌存在感。"
            )

        competitor_mentions = stats.get("competitor_mentions", {})
        if competitor_mentions:
            top_comp = max(competitor_mentions, key=competitor_mentions.get)
            top_comp_count = competitor_mentions[top_comp]
            recs.append(
                f"竞品「{top_comp}」本周获得 {top_comp_count} 次提及，建议关注其产品动态及用户评价，"
                "适时发布对比内容。"
            )

        mention_trend = trends.get("mention_trend", "flat")
        if mention_trend == "down":
            recs.append(
                "本周提及量较上周下降，建议检查关键词覆盖范围，或通过活动/内容激发社区讨论。"
            )
        elif mention_trend == "up":
            recs.append(
                "本周提及量较上周上升，建议持续跟踪热点话题，捕捉增长中的声量机会。"
            )

        if not recs:
            recs.append("本周数据平稳，继续保持常规监控节奏，关注新兴话题与社区反馈。")

        return recs

    # ------------------------------------------------------------------
    # Previous week stats
    # ------------------------------------------------------------------

    def _get_previous_week_stats(self, current_week_start: datetime) -> dict:
        """Get stats from the previous week for trend comparison."""
        prev_start = current_week_start - timedelta(days=7)
        prev_end = current_week_start
        self.logger.info(
            f"查询上周数据: {prev_start.date()} ~ {(prev_end - timedelta(seconds=1)).date()}"
        )
        try:
            prev_records = self._query_week_data(prev_start, prev_end)
            self.logger.info(f"上周记录数: {len(prev_records)}")
            return self._aggregate_stats(prev_records)
        except Exception as e:
            self.logger.warning(f"获取上周数据失败，趋势比较将跳过: {e}")
            return {}

    # ------------------------------------------------------------------
    # Page creation
    # ------------------------------------------------------------------

    def _create_report_page(self, week: str, content_blocks: list[dict]) -> str:
        """Create a new Notion database entry with the report content and properties.
        Title: 'Omada Pulse Weekly Report - {week}'
        Returns the page URL.
        """
        title = f"Omada Pulse Weekly Report - {week}"

        stats = self._last_stats
        trends = self._last_trends

        dist = stats.get("sentiment_distribution", {})
        total = stats.get("total_mentions", 0) or 1
        pos = dist.get("positive", 0)
        neg = dist.get("negative", 0)

        trend_map = {"up": "上升", "down": "下降", "flat": "持平"}

        top_topics = stats.get("top_topics", [])
        topics_text = "\n".join(f"{i+1}. {t}（{c}条）" for i, (t, c) in enumerate(top_topics[:5])) if top_topics else "暂无数据"

        competitor_mentions = stats.get("competitor_mentions", {})
        comp_text = "\n".join(f"{comp}：{count}条" for comp, count in sorted(competitor_mentions.items(), key=lambda x: x[1], reverse=True)[:8]) if competitor_mentions else "暂无数据"

        recommendations = self._generate_recommendations(stats, trends)
        recs_text = "\n".join(f"{i+1}. {r}" for i, r in enumerate(recommendations[:3]))

        properties = {
            "报告标题": {"title": [{"text": {"content": title}}]},
            "周报周期": {"select": {"name": week}},
            "报告日期": {"date": {"start": datetime.now(timezone.utc).date().isoformat()}},
            "总提及量": {"number": stats.get("total_mentions", 0)},
            "平均情感分数": {"number": stats.get("avg_sentiment_score", 0.0)},
            "正面占比": {"number": pos / total if total else 0},
            "负面占比": {"number": neg / total if total else 0},
            "总互动量": {"number": stats.get("total_engagement", 0)},
            "提及趋势": {"select": {"name": trend_map.get(trends.get("mention_trend", "flat"), "持平")}},
            "情感趋势": {"select": {"name": trend_map.get(trends.get("sentiment_trend", "flat"), "持平")}},
            "热门话题": {"rich_text": [{"text": {"content": topics_text[:2000]}}]},
            "高价值机会数": {"number": len(stats.get("opportunity_posts", []))},
            "KOL 活动数": {"number": len(stats.get("kol_activity", []))},
            "竞品提及摘要": {"rich_text": [{"text": {"content": comp_text[:2000]}}]},
            "行动建议": {"rich_text": [{"text": {"content": recs_text[:2000]}}]},
            "报告状态": {"select": {"name": "草稿"}},
        }

        page_body = {
            "parent": {"type": "database_id", "database_id": REPORT_DATABASE_ID},
            "properties": properties,
            "children": content_blocks[:100],
        }

        try:
            resp = requests.post(
                f"{NOTION_API_BASE}/pages",
                headers=self._headers,
                json=page_body,
                timeout=30,
            )
            resp.raise_for_status()
            page_data = resp.json()
        except requests.RequestException as e:
            self.logger.error(f"创建报告页面失败: {e}")
            if hasattr(e, 'response') and e.response is not None:
                self.logger.error(f"Response: {e.response.text[:500]}")
            raise

        page_id = page_data.get("id", "")
        page_url = page_data.get("url", f"https://www.notion.so/{page_id.replace('-', '')}")

        remaining_blocks = content_blocks[100:]
        if remaining_blocks:
            self._append_blocks_in_batches(page_id, remaining_blocks)

        self.logger.info(f"报告页面已创建: {page_url}")
        return page_url

    def _append_blocks_in_batches(self, page_id: str, blocks: list[dict], batch_size: int = 100):
        """Append blocks to an existing page in batches of up to 100."""
        for i in range(0, len(blocks), batch_size):
            batch = blocks[i: i + batch_size]
            try:
                resp = requests.patch(
                    f"{NOTION_API_BASE}/blocks/{page_id}/children",
                    headers=self._headers,
                    json={"children": batch},
                    timeout=30,
                )
                resp.raise_for_status()
                self.logger.debug(
                    f"追加内容块 {i + 1}~{i + len(batch)}/{len(blocks)} 成功"
                )
            except requests.RequestException as e:
                self.logger.error(f"追加内容块失败 (batch {i // batch_size + 1}): {e}")


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def create_generator(report_parent_page_id: str = None) -> WeeklyReportGenerator:
    """Create a WeeklyReportGenerator using settings from config."""
    # Ensure config is initialised
    from config.settings import initialize_configs, notion_config as _nc
    if _nc is None:
        initialize_configs()
    from config.settings import notion_config as nc
    token = nc.token
    database_id = WeeklyReportGenerator.DATABASE_ID
    return WeeklyReportGenerator(
        notion_token=token,
        database_id=database_id,
        report_parent_page_id=report_parent_page_id,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="生成 Omada Pulse 周报")
    parser.add_argument("--week", type=str, default=None, help="ISO week, e.g. 2026-W10")
    parser.add_argument("--parent-page", type=str, default=None, help="[已弃用] Parent Notion page ID (reports now write to REPORT_DATABASE_ID)")
    args = parser.parse_args()

    generator = create_generator(report_parent_page_id=args.parent_page)
    url = generator.generate_report(week=args.week)
    print(f"报告已创建: {url}")
