"""AI batch filter for post relevance screening."""
import json
import logging
import re
from typing import Optional

from .providers import LLMProvider

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a relevance filter for a Reddit monitoring system tracking the TP-Link Omada networking product line (enterprise/SMB access points, switches, gateways, SDN controllers) and related competitive landscape.

Your job: Given a batch of Reddit posts (title + metadata), judge each post's relevance to Omada product monitoring. Consider:

RELEVANT topics (score 0.5-1.0):
- Direct mentions of Omada, TP-Link networking products (EAP, SG, ER series, OC controllers), Omada SDN
- Comparisons between Omada and competitors (UniFi, Aruba, Cisco Meraki, Ruckus, Ruijie/Reyee, etc.)
- Network infrastructure discussions where Omada is a plausible recommendation or is being evaluated
- Issues, bugs, firmware discussions about TP-Link enterprise/SMB products
- User experience reports with Omada deployments
- MSP/IT service provider discussions about network equipment selection

PARTIALLY RELEVANT (score 0.3-0.49):
- General enterprise WiFi/switching discussions without brand mentions but in relevant subreddits
- Competitor-only threads that inform competitive positioning (UniFi issues, Meraki pricing complaints)
- Home networking questions where Omada could be relevant but isn't mentioned

NOT RELEVANT (score 0.0-0.29):
- Consumer TP-Link products (Deco mesh, Archer routers, Tapo, Kasa smart home)
- Topics unrelated to networking (gaming, general tech support, phones, etc.)
- Posts about EAP authentication protocol (not TP-Link EAP access points)
- Pure software/programming discussions

For each post, return a JSON object with these fields:
- post_id: string (the Reddit post ID from the input)
- relevance_score: float 0.0-1.0
- topic_category: one of ["product_issue", "feature_request", "deployment", "comparison", "recommendation_ask", "firmware_update", "general_discussion", "competitor_intel", "positive_feedback", "negative_feedback", "not_relevant"]
- sentiment_quick: one of ["positive", "negative", "neutral", "mixed"]
- should_collect_comments: boolean (true if the discussion likely contains valuable user feedback, technical details, or competitive insights)
- brief_reason: string, max 20 words explaining the judgment

Return ONLY a JSON array. No markdown fences. No extra text."""

USER_PROMPT_TEMPLATE = """Evaluate these {n} Reddit posts for Omada monitoring relevance:

{posts_json}

Return a JSON array with one object per post."""


class AIBatchFilter:
    """Batch filter posts using an LLM for relevance scoring."""

    def __init__(
        self,
        provider: LLMProvider,
        relevance_threshold: float = 0.4,
        batch_size: int = 15,
    ):
        self.provider = provider
        self.relevance_threshold = relevance_threshold
        self.batch_size = batch_size

    def _build_batch_payload(self, posts: list[dict]) -> str:
        """Build compact JSON payload for a batch of posts."""
        items = []
        for p in posts:
            items.append({
                "post_id": p["id"],
                "subreddit": p.get("subreddit", ""),
                "title": p.get("title", ""),
                "selftext_preview": (p.get("selftext", "") or "")[:300],
                "score": p.get("score", 0),
                "num_comments": p.get("num_comments", 0),
            })
        return json.dumps(items, ensure_ascii=False)

    def _parse_response(self, text: str, post_ids: set[str]) -> list[dict]:
        """Parse LLM response into structured results."""
        # Try direct JSON parse
        text = text.strip()
        # Remove markdown fences if present
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract JSON array from text
            match = re.search(r"\[.*\]", text, re.DOTALL)
            if match:
                try:
                    results = json.loads(match.group())
                except json.JSONDecodeError:
                    logger.error("Failed to parse AI filter response")
                    return []
            else:
                logger.error("No JSON array found in AI filter response")
                return []

        if not isinstance(results, list):
            logger.error(f"Expected list, got {type(results)}")
            return []

        # Validate and normalize results
        valid = []
        for r in results:
            if not isinstance(r, dict):
                continue
            pid = r.get("post_id", "")
            if pid not in post_ids:
                continue
            valid.append({
                "post_id": pid,
                "relevance_score": float(r.get("relevance_score", 0.0)),
                "topic_category": str(r.get("topic_category", "not_relevant")),
                "sentiment_quick": str(r.get("sentiment_quick", "neutral")),
                "should_collect_comments": bool(r.get("should_collect_comments", False)),
                "brief_reason": str(r.get("brief_reason", ""))[:200],
                "filter_model": self.provider.model_name,
            })

        return valid

    def filter_batch(self, posts: list[dict]) -> list[dict]:
        """Send one batch to LLM, parse response, return results."""
        if not posts:
            return []

        payload = self._build_batch_payload(posts)
        user_prompt = USER_PROMPT_TEMPLATE.format(n=len(posts), posts_json=payload)
        post_ids = {p["id"] for p in posts}

        try:
            response = self.provider.complete(SYSTEM_PROMPT, user_prompt)
            results = self._parse_response(response, post_ids)
        except Exception as e:
            logger.error(f"AI filter batch failed: {e}")
            return []

        # Fill in missing post IDs with default (not_relevant)
        seen = {r["post_id"] for r in results}
        for pid in post_ids - seen:
            logger.warning(f"Post {pid} missing from AI response, defaulting to not_relevant")
            results.append({
                "post_id": pid,
                "relevance_score": 0.0,
                "topic_category": "not_relevant",
                "sentiment_quick": "neutral",
                "should_collect_comments": False,
                "brief_reason": "Missing from AI response",
                "filter_model": self.provider.model_name,
            })

        return results

    def filter_all(self, posts: list[dict]) -> list[dict]:
        """Process all posts in batches. Returns aggregated results."""
        all_results = []
        total = len(posts)

        for i in range(0, total, self.batch_size):
            batch = posts[i:i + self.batch_size]
            batch_num = i // self.batch_size + 1
            total_batches = (total + self.batch_size - 1) // self.batch_size
            logger.info(f"AI filter batch {batch_num}/{total_batches} ({len(batch)} posts)")

            results = self.filter_batch(batch)
            all_results.extend(results)

            passed = sum(1 for r in results if r["relevance_score"] >= self.relevance_threshold)
            logger.info(f"  → {passed}/{len(batch)} passed threshold ({self.relevance_threshold})")

        return all_results
