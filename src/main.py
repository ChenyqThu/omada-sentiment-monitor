"""
Omada 舆情监控系统 - 主程序入口
"""
import asyncio
import sys
import os
import signal
from datetime import datetime
from typing import List

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import validate_config, get_config_summary, system_config
from src.utils.logger import log_system_info, main_logger, log_error
from src.utils.cache import cache_manager
from src.collectors.reddit_collector import RedditCollector
from src.analyzers.analyzer_factory import analyzer_factory

class OmadaMonitor:
    """Omada 舆情监控主程序"""
    
    def __init__(self):
        self.running = False
        self.reddit_collector = None
        self.analyzer = None
        self.notion_client = None
        
        # 统计信息
        self.stats = {
            'total_posts_collected': 0,
            'total_posts_analyzed': 0,
            'total_posts_synced': 0,
            'errors': 0,
            'last_collection_time': None,
            'last_sync_time': None
        }
        
        # 信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """信号处理器"""
        main_logger.info(f"收到信号 {signum}，准备关闭...")
        self.running = False
    
    def initialize(self) -> bool:
        """初始化系统"""
        try:
            main_logger.info("初始化 Omada 舆情监控系统...")
            
            # 验证配置
            if not validate_config():
                main_logger.error("配置验证失败，请检查环境变量")
                return False
            
            # 输出配置摘要
            config_summary = get_config_summary()
            main_logger.info("配置摘要:")
            for category, info in config_summary.items():
                main_logger.info(f"  {category}: {info}")
            
            # 初始化各个组件
            self.reddit_collector = RedditCollector()
            
            # 初始化 AI 分析器
            from config.settings import ai_analysis_config
            if ai_analysis_config.enabled:
                try:
                    self.analyzer = analyzer_factory.create_analyzer()
                    main_logger.info(f"AI 分析器初始化完成: {ai_analysis_config.analyzer_type}")
                except Exception as e:
                    main_logger.warning(f"AI 分析器初始化失败: {e}")
                    if ai_analysis_config.required:
                        return False
            
            # 初始化 Notion 客户端
            from config.settings import notion_config
            if notion_config.enabled:
                try:
                    from src.storage.notion_client import NotionSyncClient
                    self.notion_client = NotionSyncClient()
                    main_logger.info("Notion 客户端初始化完成")
                except Exception as e:
                    main_logger.warning(f"Notion 客户端初始化失败: {e}")
                    if notion_config.required:
                        return False
            
            # 清理过期缓存
            expired_count = cache_manager.cleanup_expired()
            if expired_count > 0:
                main_logger.info(f"清理了 {expired_count} 条过期缓存")
            
            main_logger.info("系统初始化完成")
            return True
            
        except Exception as e:
            log_error(e, "系统初始化失败")
            return False
    
    def run_single_collection(self) -> bool:
        """运行单次数据采集"""
        try:
            start_time = datetime.now()
            main_logger.info("开始执行数据采集...")
            
            # 1. 采集 Reddit 数据
            posts = self.reddit_collector.collect_posts()
            
            if not posts:
                main_logger.info("本次采集未发现新的相关内容")
                return True
            
            main_logger.info(f"采集到 {len(posts)} 个新帖子")
            self.stats['total_posts_collected'] += len(posts)
            self.stats['last_collection_time'] = datetime.now().isoformat()
            
            # 2. AI 分析
            analyses = []
            if self.analyzer:
                main_logger.info("开始 AI 分析...")
                from config.settings import ai_analysis_config
                
                for i, post in enumerate(posts):
                    try:
                        # 分析帖子内容和评论
                        full_text = f"{post.title}\n\n{post.content}"
                        if post.comments:
                            comment_text = "\n".join([c.content for c in post.comments[:5]])  # 只分析前5条评论
                            full_text += f"\n\n评论:\n{comment_text}"
                        
                        analysis = self.analyzer.analyze_comprehensive(
                            full_text,
                            enable_sentiment=ai_analysis_config.enable_sentiment,
                            enable_key_phrases=ai_analysis_config.enable_key_phrases,
                            enable_topic=ai_analysis_config.enable_topic_classification
                        )
                        
                        analyses.append(analysis)
                        self.stats['total_posts_analyzed'] += 1
                        
                        if not analysis.error:
                            main_logger.debug(f"帖子 {i+1} 分析完成: {analysis.sentiment.sentiment if analysis.sentiment else 'N/A'}")
                        else:
                            main_logger.warning(f"帖子 {i+1} 分析失败: {analysis.error}")
                            
                    except Exception as e:
                        main_logger.error(f"分析帖子 {i+1} 时发生异常: {e}")
                        analyses.append(None)
                        self.stats['errors'] += 1
                
                main_logger.info(f"AI 分析完成，成功分析 {sum(1 for a in analyses if a and not a.error)} 个帖子")
            
            # 3. 同步到 Notion
            if self.notion_client:
                main_logger.info("开始同步到 Notion...")
                try:
                    sync_results = self.notion_client.sync_posts_batch(posts, analyses)
                    
                    self.stats['total_posts_synced'] += sync_results['success_count']
                    self.stats['last_sync_time'] = datetime.now().isoformat()
                    
                    # 详细的同步结果日志
                    main_logger.info(f"Notion 同步完成:")
                    main_logger.info(f"  ✅ 成功: {sync_results['success_count']} 个")
                    main_logger.info(f"    - 新建: {sync_results.get('created_count', 0)} 个")
                    main_logger.info(f"    - 更新: {sync_results.get('updated_count', 0)} 个")
                    main_logger.info(f"  ⏭️ 跳过: {sync_results.get('skipped_count', 0)} 个 (无需更新)")
                    main_logger.info(f"  ❌ 失败: {sync_results['failed_count']} 个")
                    
                    if sync_results['errors']:
                        for error in sync_results['errors'][:3]:  # 只显示前3个错误
                            main_logger.warning(f"同步错误: {error}")
                    
                except Exception as e:
                    main_logger.error(f"Notion 同步失败: {e}")
                    self.stats['errors'] += 1
            
            # 4. 显示采集结果摘要
            self._log_collection_summary(posts, analyses)
            
            # 记录执行时间
            duration = (datetime.now() - start_time).total_seconds()
            main_logger.info(f"完整流程执行完成，耗时: {duration:.2f}秒")
            
            return True
            
        except Exception as e:
            log_error(e, "数据采集失败")
            return False
    
    def _log_collection_summary(self, posts: List, analyses: List = None):
        """记录采集结果摘要"""
        if not posts:
            return
        
        # 按 subreddit 统计
        subreddit_stats = {}
        sentiment_stats = {'positive': 0, 'neutral': 0, 'negative': 0}
        total_score = 0
        total_comments = 0
        
        for i, post in enumerate(posts):
            # Subreddit 统计
            subreddit = post.subreddit
            if subreddit not in subreddit_stats:
                subreddit_stats[subreddit] = {'count': 0, 'avg_score': 0, 'total_score': 0}
            
            subreddit_stats[subreddit]['count'] += 1
            subreddit_stats[subreddit]['total_score'] += post.score
            subreddit_stats[subreddit]['avg_score'] = subreddit_stats[subreddit]['total_score'] / subreddit_stats[subreddit]['count']
            
            # 总体统计
            total_score += post.score
            total_comments += post.num_comments
            
            # 情感统计
            if analyses and i < len(analyses) and analyses[i] and analyses[i].sentiment:
                sentiment = analyses[i].sentiment.sentiment
                if sentiment in sentiment_stats:
                    sentiment_stats[sentiment] += 1
        
        # 输出统计信息
        main_logger.info("=== 采集结果摘要 ===")
        main_logger.info(f"总帖子数: {len(posts)}")
        main_logger.info(f"平均分数: {total_score/len(posts):.1f}")
        main_logger.info(f"总评论数: {total_comments}")
        
        # AI 分析统计
        if analyses:
            analyzed_count = sum(1 for a in analyses if a and not a.error)
            main_logger.info(f"AI 分析成功: {analyzed_count}/{len(posts)}")
            
            if analyzed_count > 0:
                main_logger.info("情感分布:")
                total_sentiment = sum(sentiment_stats.values())
                if total_sentiment > 0:
                    for sentiment, count in sentiment_stats.items():
                        percentage = (count / total_sentiment) * 100
                        main_logger.info(f"  {sentiment}: {count} ({percentage:.1f}%)")
        
        main_logger.info("各 Subreddit 统计:")
        for subreddit, stats in subreddit_stats.items():
            main_logger.info(f"  r/{subreddit}: {stats['count']} 帖子, 平均分数: {stats['avg_score']:.1f}")
        
        # 显示热门帖子
        top_posts = sorted(posts, key=lambda p: p.score, reverse=True)[:3]
        main_logger.info("热门帖子:")
        for i, post in enumerate(top_posts, 1):
            main_logger.info(f"  {i}. {post.title[:50]}... (r/{post.subreddit}, 分数: {post.score})")
        
        # 显示系统累计统计
        main_logger.info("=== 系统统计 ===")
        main_logger.info(f"累计采集帖子: {self.stats['total_posts_collected']}")
        main_logger.info(f"累计分析帖子: {self.stats['total_posts_analyzed']}")
        main_logger.info(f"累计同步帖子: {self.stats['total_posts_synced']}")
        main_logger.info(f"累计错误数: {self.stats['errors']}")
    
    def run_continuous(self):
        """持续运行模式"""
        main_logger.info("进入持续运行模式...")
        self.running = True
        
        while self.running:
            try:
                # 执行一次采集
                success = self.run_single_collection()
                
                if not success:
                    main_logger.error("数据采集失败，等待下次尝试...")
                
                # 等待下次执行
                if self.running:
                    import time
                    from config.settings import monitoring_config
                    
                    wait_time = monitoring_config.check_interval
                    main_logger.info(f"等待 {wait_time} 秒后进行下次采集...")
                    
                    # 分段等待，以便响应中断信号
                    waited = 0
                    while waited < wait_time and self.running:
                        time.sleep(min(10, wait_time - waited))
                        waited += 10
                
            except KeyboardInterrupt:
                main_logger.info("收到中断信号，正在退出...")
                break
            except Exception as e:
                log_error(e, "运行时发生异常")
                if self.running:
                    import time
                    time.sleep(60)  # 发生异常时等待1分钟再重试
        
        main_logger.info("程序已退出")
    
    def health_check(self) -> dict:
        """系统健康检查"""
        health_status = {
            'timestamp': datetime.now().isoformat(),
            'overall_status': 'healthy',
            'components': {}
        }
        
        try:
            # Reddit 采集器健康检查
            if self.reddit_collector:
                reddit_health = self.reddit_collector.health_check()
                health_status['components']['reddit_collector'] = reddit_health
                
                if reddit_health.get('status') != 'healthy':
                    health_status['overall_status'] = 'unhealthy'
            
            # AI 分析器健康检查
            if self.analyzer:
                analyzer_health = analyzer_factory.health_check_all()
                from config.settings import ai_analysis_config
                current_analyzer = ai_analysis_config.analyzer_type
                
                health_status['components']['analyzer'] = {
                    'current_analyzer': current_analyzer,
                    'status': analyzer_health.get(current_analyzer, {}).get('status', 'unknown'),
                    'all_analyzers': analyzer_health
                }
                
                if analyzer_health.get(current_analyzer, {}).get('status') != 'healthy':
                    health_status['overall_status'] = 'unhealthy'
            
            # Notion 客户端健康检查
            if self.notion_client:
                notion_health = self.notion_client.health_check()
                health_status['components']['notion'] = notion_health
                
                if notion_health.get('status') != 'healthy':
                    health_status['overall_status'] = 'unhealthy'
            
            # 缓存系统健康检查
            cache_stats = cache_manager.get_cache_stats()
            health_status['components']['cache'] = {
                'status': 'healthy' if cache_stats.get('enabled') else 'disabled',
                'stats': cache_stats
            }
            
            # 系统配置检查
            config_valid = validate_config()
            health_status['components']['config'] = {
                'status': 'healthy' if config_valid else 'unhealthy',
                'valid': config_valid
            }
            
            if not config_valid:
                health_status['overall_status'] = 'unhealthy'
            
        except Exception as e:
            health_status['overall_status'] = 'error'
            health_status['error'] = str(e)
            log_error(e, "健康检查失败")
        
        return health_status
    
    def cleanup(self):
        """清理资源"""
        try:
            main_logger.info("开始清理系统资源...")
            
            # 清理缓存
            if hasattr(self, 'cache_manager'):
                cache_manager.cleanup_expired()
            
            main_logger.info("资源清理完成")
            
        except Exception as e:
            log_error(e, "资源清理失败")

def test_analyzer():
    """测试AI分析器功能"""
    print("🧪 AI 分析器测试")
    print("=" * 50)
    
    try:
        from src.analyzers.analyzer_factory import analyzer_factory
        
        # 显示可用分析器
        print("🔍 可用分析器:")
        analyzers = analyzer_factory.get_available_analyzers()
        for name, info in analyzers.items():
            status = "✅" if info['available'] else "❌"
            print(f"  {status} {name}: {info['description']}")
            if not info['available'] and 'error' in info:
                print(f"     错误: {info['error']}")
        
        print("\n🏥 健康检查:")
        health_results = analyzer_factory.health_check_all()
        for name, result in health_results.items():
            status_icon = "✅" if result['status'] == 'healthy' else "❌" if result['status'] == 'unhealthy' else "⚠️"
            print(f"  {status_icon} {name}: {result['status']}")
            if result['status'] == 'unhealthy':
                print(f"     错误: {result.get('error', '未知错误')}")
        
        # 测试分析功能
        print("\n🧪 功能测试:")
        
        # 获取当前配置的分析器
        from config.settings import ai_analysis_config
        analyzer = analyzer_factory.create_analyzer()
        
        print(f"使用分析器: {ai_analysis_config.analyzer_type}")
        
        # 测试文本
        test_texts = [
            "This TP-Link Omada access point is amazing! Great coverage and stable connection.",
            "My Archer router keeps disconnecting. Very frustrated with this product.",
            "Looking for recommendations on mesh network setup for small office."
        ]
        
        for i, text in enumerate(test_texts, 1):
            print(f"\n📝 测试文本 {i}: \"{text[:50]}...\"")
            
            result = analyzer.analyze_comprehensive(
                text,
                enable_sentiment=ai_analysis_config.enable_sentiment,
                enable_key_phrases=ai_analysis_config.enable_key_phrases,
                enable_topic=ai_analysis_config.enable_topic_classification
            )
            
            if result.error:
                print(f"❌ 分析失败: {result.error}")
                continue
            
            if result.sentiment:
                print(f"😊 情感: {result.sentiment.sentiment} (置信度: {result.sentiment.confidence:.2f}, 分数: {result.sentiment.score:.2f})")
            
            if result.key_phrases and result.key_phrases.phrases:
                print(f"🔑 关键词: {result.key_phrases.phrases[:5]}")
            
            if result.topics and result.topics.topics:
                print(f"📂 主题: {result.topics.topics}")
            
            if result.summary:
                print(f"📄 摘要: {result.summary}")
            
            print(f"⏱️  处理时间: {result.processing_time:.3f}s")
        
        print("\n✅ 分析器测试完成")
        
    except Exception as e:
        print(f"❌ 分析器测试失败: {e}")
        log_error(e, "分析器测试异常")

def test_notion_sync():
    """测试 Notion 同步功能"""
    print("🧪 Notion 同步功能测试")
    print("=" * 50)
    
    try:
        from config.settings import notion_config
        
        if not notion_config.enabled:
            print("❌ Notion 配置未启用")
            print("请确保设置了以下环境变量:")
            print("  - NOTION_TOKEN")
            print("  - NOTION_DATABASE_ID")
            return
        
        print(f"✅ Notion 配置已启用")
        print(f"📊 Database ID: {notion_config.database_id[:8]}...")
        
        # 测试连接
        print("\n🔗 测试 Notion 连接...")
        from src.storage.notion_client import NotionSyncClient
        client = NotionSyncClient()
        
        health = client.health_check()
        print(f"状态: {health['status']}")
        
        if health['status'] == 'healthy':
            print(f"✅ 数据库标题: {health.get('database_title', 'Unknown')}")
            print(f"📊 字段数量: {health.get('properties_count', 0)}")
            
            # 测试同步示例数据
            print("\n📝 测试数据同步...")
            from src.collectors.reddit_collector import RedditPost
            from datetime import datetime, timezone
            
            # 创建测试帖子
            test_post = RedditPost(
                id="notion_test_" + datetime.now().strftime("%Y%m%d_%H%M%S"),
                title="Notion 同步测试帖子",
                content="这是一个测试帖子，用于验证 Notion 同步功能是否正常工作。",
                subreddit="test",
                author="test_user",
                created_time=datetime.now(timezone.utc),
                score=10,
                num_comments=0,
                url="https://reddit.com/test",
                permalink="https://reddit.com/test/permalink",
                upvote_ratio=0.95,
                is_self=True,
                selftext="这是一个测试帖子，用于验证 Notion 同步功能是否正常工作。",
                keywords_matched=["test"],
                relevance_score=1.0
            )
            
            page_id = client.sync_post(test_post)
            
            if page_id:
                print(f"✅ 同步成功！页面 ID: {page_id}")
                print("✅ 测试完成，请检查您的 Notion Database")
            else:
                print("❌ 同步失败")
        else:
            print(f"❌ 连接失败: {health.get('error', 'Unknown error')}")
        
    except Exception as e:
        print(f"❌ Notion 测试失败: {e}")
        log_error(e, "Notion 测试异常")

def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Omada 舆情监控系统')
    parser.add_argument('--mode', choices=['single', 'continuous', 'health'], 
                       default='single', help='运行模式')
    parser.add_argument('--config-check', action='store_true', help='仅检查配置')
    parser.add_argument('--cache-clear', action='store_true', help='清空缓存')
    parser.add_argument('--cache-stats', action='store_true', help='显示缓存统计')
    parser.add_argument('--debug', action='store_true', help='调试模式：降低阈值，显示详细信息')
    parser.add_argument('--test-analyzer', action='store_true', help='测试AI分析器功能')
    parser.add_argument('--test-notion', action='store_true', help='测试Notion同步功能')
    
    args = parser.parse_args()
    
    # 调试模式：临时调整配置
    if args.debug:
        print("🔍 启用调试模式")
        from config.settings import monitoring_config
        monitoring_config.relevance_threshold = 0.1  # 大幅降低阈值
        print(f"📊 相关性阈值降低至: {monitoring_config.relevance_threshold}")
        print(f"🔍 关键词: {monitoring_config.primary_keywords}")
    
    # 记录系统启动信息
    log_system_info()
    
    # 配置检查模式
    if args.config_check:
        if validate_config():
            print("✅ 配置验证通过")
            config_summary = get_config_summary()
            for category, info in config_summary.items():
                print(f"{category}: {info}")
            sys.exit(0)
        else:
            print("❌ 配置验证失败")
            sys.exit(1)
    
    # 缓存管理
    if args.cache_clear:
        if cache_manager.clear_all():
            print("✅ 缓存已清空")
        else:
            print("❌ 清空缓存失败")
        sys.exit(0)
    
    if args.cache_stats:
        stats = cache_manager.get_cache_stats()
        print("缓存统计信息:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
        sys.exit(0)
    
    if args.test_analyzer:
        test_analyzer()
        sys.exit(0)
    
    if args.test_notion:
        test_notion_sync()
        sys.exit(0)
    
    # 创建监控实例
    monitor = OmadaMonitor()
    
    try:
        # 初始化系统
        if not monitor.initialize():
            main_logger.error("系统初始化失败")
            sys.exit(1)
        
        # 根据模式运行
        if args.mode == 'single':
            main_logger.info("执行单次数据采集...")
            success = monitor.run_single_collection()
            sys.exit(0 if success else 1)
            
        elif args.mode == 'continuous':
            main_logger.info("启动持续监控模式...")
            monitor.run_continuous()
            
        elif args.mode == 'health':
            health = monitor.health_check()
            print(f"系统健康状态: {health['overall_status']}")
            
            for component, status in health['components'].items():
                print(f"  {component}: {status.get('status', 'unknown')}")
            
            if health['overall_status'] != 'healthy':
                sys.exit(1)
    
    except KeyboardInterrupt:
        main_logger.info("程序被用户中断")
    except Exception as e:
        log_error(e, "程序运行异常")
        sys.exit(1)
    finally:
        monitor.cleanup()

if __name__ == "__main__":
    main() 