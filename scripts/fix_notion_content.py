"""Fix duplicated content on Notion pages.

1. Replace all KOL page content (fix duplication from previous insert-based syncs)
2. Replace all post page content with new <details> toggle format for comments

Usage:
    python scripts/fix_notion_content.py --kol          # fix KOL pages only
    python scripts/fix_notion_content.py --posts        # fix post pages only
    python scripts/fix_notion_content.py --all          # fix both
    python scripts/fix_notion_content.py --test N       # test on N pages first
"""
import argparse
import os
import sys
import time

project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from src.db.database import Database
from src.db.repository import PostRepository
from src.storage.notion_client import NotionSyncClient
from config.settings import ai_filter_config


def fix_kol_pages(repo: PostRepository, notion: NotionSyncClient, limit: int = 0):
    """Replace content on all KOL pages to fix duplication."""
    authors = repo.get_kol_authors(min_tier="watch")
    if limit:
        authors = authors[:limit]

    print(f"\n{'='*60}")
    print(f"KOL 内容修复: {len(authors)} 个作者")
    print(f"{'='*60}")

    success = 0
    errors = []

    for i, author in enumerate(authors, 1):
        username = author["username"]
        try:
            posts = repo.get_author_posts(username)
            existing = notion._find_kol_page(username)

            if not existing:
                print(f"  [{i}/{len(authors)}] {username}: 页面不存在，跳过")
                continue

            page_id = existing["id"]
            markdown = notion._build_kol_markdown(author, posts)
            if markdown:
                ok = notion._replace_page_markdown(page_id, markdown)
                if ok:
                    success += 1
                    print(f"  [{i}/{len(authors)}] {username}: 内容已替换 ✓")
                else:
                    errors.append(username)
                    print(f"  [{i}/{len(authors)}] {username}: 替换失败 ✗")
            else:
                print(f"  [{i}/{len(authors)}] {username}: 无内容可写")

            # Rate limit: ~3 requests per page (find + read + replace)
            if i % 10 == 0:
                time.sleep(1)

        except Exception as e:
            errors.append(f"{username}: {e}")
            print(f"  [{i}/{len(authors)}] {username}: 异常 {e}")

    print(f"\nKOL 修复完成: {success}/{len(authors)} 成功, {len(errors)} 失败")
    if errors:
        print(f"失败列表: {errors[:10]}")


def fix_post_pages(repo: PostRepository, notion: NotionSyncClient, limit: int = 0):
    """Replace content on post pages with new toggle format."""
    # Get all posts synced to Notion that also have comments
    rows = repo.db.conn.execute(
        """SELECT id, notion_page_id FROM posts
           WHERE notion_page_id IS NOT NULL
           AND id IN (SELECT DISTINCT post_id FROM comments)
           ORDER BY created_utc DESC"""
    ).fetchall()
    posts_to_fix = [(r["id"], r["notion_page_id"]) for r in rows]

    if limit:
        posts_to_fix = posts_to_fix[:limit]

    print(f"\n{'='*60}")
    print(f"帖子内容修复: {len(posts_to_fix)} 篇帖子 (有评论)")
    print(f"{'='*60}")

    success = 0
    errors = []

    for i, (post_id, page_id) in enumerate(posts_to_fix, 1):
        try:
            post = repo.get_post_with_comments(post_id)
            if not post:
                continue

            comments = post.get("comments", [])
            markdown = notion._build_markdown_from_dict(post)
            if markdown:
                ok = notion._replace_page_markdown(page_id, markdown)
                if ok:
                    success += 1
                    if i <= 5 or i % 20 == 0:
                        print(f"  [{i}/{len(posts_to_fix)}] {post_id}: 内容已替换 ({len(comments)} 评论) ✓")
                else:
                    errors.append(post_id)
                    print(f"  [{i}/{len(posts_to_fix)}] {post_id}: 替换失败 ✗")

            if i % 10 == 0:
                time.sleep(1)

        except Exception as e:
            errors.append(f"{post_id}: {e}")
            print(f"  [{i}/{len(posts_to_fix)}] {post_id}: 异常 {e}")

    print(f"\n帖子修复完成: {success}/{len(posts_to_fix)} 成功, {len(errors)} 失败")
    if errors:
        print(f"失败列表: {errors[:10]}")


def main():
    parser = argparse.ArgumentParser(description="Fix Notion page content")
    parser.add_argument("--kol", action="store_true", help="Fix KOL pages")
    parser.add_argument("--posts", action="store_true", help="Fix post pages")
    parser.add_argument("--all", action="store_true", help="Fix both")
    parser.add_argument("--test", type=int, default=0, help="Limit to N pages for testing")
    args = parser.parse_args()

    if not (args.kol or args.posts or args.all):
        parser.print_help()
        return

    db = Database(ai_filter_config.db_path)
    repo = PostRepository(db)
    notion = NotionSyncClient()

    if args.kol or args.all:
        fix_kol_pages(repo, notion, limit=args.test)

    if args.posts or args.all:
        fix_post_pages(repo, notion, limit=args.test)


if __name__ == "__main__":
    main()
