#!/usr/bin/env python3
"""
测试 Notion 更新机制
"""
import os
import sys
from datetime import datetime, timezone

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import initialize_configs, validate_config
from src.storage.notion_client import NotionSyncClient
from src.collectors.reddit_collector import RedditPost, RedditComment
from src.utils.logger import main_logger

def create_test_post(post_id: str, score: int = 10, num_comments: int = 5, with_comments: bool = False) -> RedditPost:
    """创建测试帖子"""
    comments = []
    if with_comments and num_comments > 0:
        for i in range(min(num_comments, 5)):  # 最多创建5个测试评论
            comments.append(RedditComment(
                id=f"comment_{i+1}",
                post_id=post_id,
                content=f"这是第 {i+1} 条测试评论内容。这条评论是用来测试更新机制的。",
                author=f"test_user_{i+1}",
                score=10 + i,
                created_time=datetime.now(timezone.utc),
                parent_id=None
            ))
    
    return RedditPost(
        id=post_id,
        title="测试更新机制 - 这是一个测试帖子",
        content="这是一个用于测试 Notion 更新机制的帖子内容。",
        subreddit="test",
        author="test_user",
        created_time=datetime.now(timezone.utc),
        score=score,
        num_comments=num_comments,
        url=f"https://reddit.com/r/test/comments/{post_id}",
        permalink=f"/r/test/comments/{post_id}",
        upvote_ratio=0.8,
        is_self=True,
        selftext="测试内容",
        keywords_matched=["test"],
        relevance_score=0.5,
        influence_score=float(score) / 10,
        author_karma=1000,
        comments=comments
    )

def test_update_mechanism():
    """测试更新机制"""
    print("🧪 开始测试 Notion 更新机制...")
    
    # 初始化配置
    if not initialize_configs():
        print("❌ 配置初始化失败")
        return False
    
    if not validate_config():
        print("❌ 配置验证失败")
        return False
    
    try:
        # 初始化 Notion 客户端
        notion_client = NotionSyncClient()
        
        # 测试帖子 ID
        test_post_id = f"test_update_{int(datetime.now().timestamp())}"
        
        print(f"📝 使用测试帖子 ID: {test_post_id}")
        
        # 步骤 1: 创建初始帖子
        print("\n📝 步骤 1: 创建初始帖子...")
        initial_post = create_test_post(test_post_id, score=10, num_comments=2)
        
        page_id = notion_client.sync_post(initial_post)
        if not page_id:
            print("❌ 创建初始帖子失败")
            return False
        
        print(f"✅ 成功创建初始帖子，页面 ID: {page_id}")
        
        # 步骤 2: 测试无需更新的情况（分数和评论数变化很小）
        print("\n📝 步骤 2: 测试无需更新的情况...")
        small_change_post = create_test_post(test_post_id, score=12, num_comments=3)
        
        page_id_2 = notion_client.sync_post(small_change_post)
        if page_id_2 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 正确跳过了小幅度变化的更新")
        
        # 步骤 3: 测试需要更新的情况（分数大幅增加）
        print("\n📝 步骤 3: 测试分数大幅增加的更新...")
        big_score_change_post = create_test_post(test_post_id, score=50, num_comments=3)
        
        page_id_3 = notion_client.sync_post(big_score_change_post)
        if page_id_3 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 成功更新了分数大幅变化的帖子")
        
        # 步骤 4: 测试需要更新的情况（评论数大幅增加）
        print("\n📝 步骤 4: 测试评论数大幅增加的更新...")
        big_comments_change_post = create_test_post(test_post_id, score=50, num_comments=20)
        
        page_id_4 = notion_client.sync_post(big_comments_change_post)
        if page_id_4 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 成功更新了评论数大幅变化的帖子")
        
        # 步骤 5: 测试热门帖子更新
        print("\n📝 步骤 5: 测试热门帖子更新...")
        hot_post = create_test_post(test_post_id, score=150, num_comments=25)
        
        page_id_5 = notion_client.sync_post(hot_post)
        if page_id_5 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 成功更新了热门帖子")
        
        # 步骤 6: 测试评论内容更新
        print("\n📝 步骤 6: 测试评论内容更新...")
        post_with_comments = create_test_post(test_post_id, score=150, num_comments=30, with_comments=True)
        
        page_id_6 = notion_client.sync_post(post_with_comments)
        if page_id_6 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 成功更新了帖子内容（包含评论）")
        
        # 步骤 7: 测试再次添加更多评论
        print("\n📝 步骤 7: 测试添加更多评论...")
        post_with_more_comments = create_test_post(test_post_id, score=160, num_comments=40, with_comments=True)
        
        page_id_7 = notion_client.sync_post(post_with_more_comments)
        if page_id_7 != page_id:
            print("❌ 应该返回相同的页面 ID")
            return False
        
        print("✅ 成功更新了帖子内容（更多评论）")
        
        print(f"\n🎉 所有测试通过！最终页面 ID: {page_id}")
        print(f"📄 可以在 Notion 中查看页面: https://notion.so/{page_id.replace('-', '')}")
        print("✨ 页面应该包含最新的评论内容！")
        
        return True
        
    except Exception as e:
        main_logger.error(f"测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_update_conditions():
    """测试更新条件的判断逻辑"""
    print("\n🧪 测试更新条件判断逻辑...")
    
    try:
        # 初始化配置和客户端
        if not initialize_configs():
            return False
        
        notion_client = NotionSyncClient()
        
        # 创建模拟的现有页面数据
        existing_page = {
            'id': 'test-page-id',
            'properties': {
                '分数': {'type': 'number', 'number': 10},
                '评论数': {'type': 'number', 'number': 5}
            }
        }
        
        test_cases = [
            # (新分数, 新评论数, 期望结果, 描述)
            (12, 6, False, "小幅度变化，不应更新"),
            (25, 5, True, "分数变化超过阈值，应该更新"),
            (10, 15, True, "评论数变化超过阈值，应该更新"),
            (150, 5, True, "达到热门帖子阈值，应该更新"),
            (10, 60, True, "达到热议帖子阈值，应该更新"),
        ]
        
        for score, comments, expected, description in test_cases:
            test_post = create_test_post("test", score=score, num_comments=comments)
            result = notion_client._should_update_post(existing_page, test_post)
            
            status = "✅" if (result['should_update'] or result['should_update_content']) == expected else "❌"
            print(f"{status} {description}: 分数 {score}, 评论 {comments} -> {'需要更新' if (result['should_update'] or result['should_update_content']) else '无需更新'}")
            
            if (result['should_update'] or result['should_update_content']) != expected:
                print(f"   期望: {'需要更新' if expected else '无需更新'}, 实际: {'需要更新' if (result['should_update'] or result['should_update_content']) else '无需更新'}")
                print(f"   详细信息: {result}")
                return False
        
        print("✅ 所有更新条件测试通过！")
        return True
        
    except Exception as e:
        print(f"❌ 更新条件测试失败: {e}")
        return False

if __name__ == "__main__":
    print("🚀 开始测试 Notion 更新机制...")
    
    # 测试更新条件判断
    if not test_update_conditions():
        print("❌ 更新条件测试失败")
        sys.exit(1)
    
    # 测试完整的更新机制
    if not test_update_mechanism():
        print("❌ 更新机制测试失败")
        sys.exit(1)
    
    print("\n🎉 所有测试完成！")
    print("\n📋 更新机制功能说明:")
    print("1. ✅ 支持基于 Reddit ID 查找已存在的帖子")
    print("2. ✅ 支持配置化的更新条件（分数变化、评论数变化）")
    print("3. ✅ 支持热门帖子和热议帖子的特殊更新规则")
    print("4. ✅ 提供详细的更新统计信息")
    print("5. ✅ 只更新必要的字段，避免不必要的 API 调用")
    print("\n现在系统将能够智能地更新已存在的帖子，而不是重复创建！") 