"""
Reddit 数据采集器
使用 PRAW 库采集 Reddit 数据
"""
import praw
import time
import re
import os
import sys
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set
from dataclasses import dataclass, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import reddit_config, monitoring_config, SUBREDDIT_CONFIG
from src.utils.logger import LoggerMixin
from src.utils.cache import cache_manager

@dataclass
class RedditPost:
    """Reddit 帖子数据结构"""
    id: str
    title: str
    content: str
    subreddit: str
    author: str
    created_time: datetime
    score: int
    num_comments: int
    url: str
    permalink: str
    upvote_ratio: float
    is_self: bool
    selftext: str
    
    # 元数据
    keywords_matched: List[str]
    relevance_score: float
    
    # 分析数据
    influence_score: float = 0.0
    author_karma: int = 0
    comments: List['RedditComment'] = None
    
    # 新增：作者信息
    author_info: Optional[Dict] = None  # 作者详细信息
    author_kol_score: float = 0.0  # 作者 KOL 评分
    
    def __post_init__(self):
        if self.comments is None:
            self.comments = []
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        data = asdict(self)
        data['created_time'] = self.created_time.isoformat()
        return data

@dataclass  
class RedditComment:
    """Reddit 评论数据结构"""
    id: str
    post_id: str
    content: str
    author: str
    score: int
    created_time: datetime
    parent_id: Optional[str] = None
    
    # 新增：嵌套评论支持
    depth: int = 0  # 评论嵌套深度
    replies: List['RedditComment'] = None  # 子评论
    
    # 新增：作者信息
    author_info: Optional[Dict] = None  # 作者详细信息
    author_kol_score: float = 0.0  # 作者 KOL 评分
    
    def __post_init__(self):
        if self.replies is None:
            self.replies = []
    
    def to_dict(self) -> Dict:
        """转换为字典格式"""
        data = asdict(self)
        data['created_time'] = self.created_time.isoformat()
        return data

class RateLimiter:
    """速率限制器"""
    
    def __init__(self, max_calls: int, period: int):
        self.max_calls = max_calls
        self.period = period
        self.calls = []
    
    def can_proceed(self) -> bool:
        """检查是否可以继续调用"""
        now = time.time()
        # 清理过期的调用记录
        self.calls = [call_time for call_time in self.calls if now - call_time < self.period]
        return len(self.calls) < self.max_calls
    
    def add_call(self):
        """记录一次调用"""
        self.calls.append(time.time())
    
    def wait_if_needed(self):
        """如果需要，等待到可以调用"""
        while not self.can_proceed():
            time.sleep(1)

class RedditCollector(LoggerMixin):
    """Reddit 数据采集器"""
    
    def __init__(self):
        self.reddit = None
        self.rate_limiter = RateLimiter(
            reddit_config.rate_limit_calls,
            reddit_config.rate_limit_period
        )
        self.keywords = self._compile_keywords()
        self._initialize_reddit()
    
    def _initialize_reddit(self):
        """初始化 Reddit API 连接"""
        try:
            self.reddit = praw.Reddit(
                client_id=reddit_config.client_id,
                client_secret=reddit_config.client_secret,
                user_agent=reddit_config.user_agent,
                ratelimit_seconds=600  # 10分钟的速率限制缓冲
            )
            
            # 测试连接
            self.logger.info(f"Reddit API 连接成功，用户代理: {reddit_config.user_agent}")
            
        except Exception as e:
            self.logger.error(f"初始化 Reddit API 失败: {e}")
            raise
    
    def _compile_keywords(self) -> Dict[str, List[re.Pattern]]:
        """编译关键词正则表达式"""
        compiled_keywords = {}
        
        for category in ['primary_keywords', 'secondary_keywords', 'competitor_keywords']:
            keywords = getattr(monitoring_config, category, [])
            compiled_keywords[category] = []
            
            for keyword in keywords:
                try:
                    # 创建不区分大小写的正则表达式
                    pattern = re.compile(r'\b' + re.escape(keyword.strip()) + r'\b', re.IGNORECASE)
                    compiled_keywords[category].append(pattern)
                except re.error as e:
                    self.logger.warning(f"关键词正则编译失败 '{keyword}': {e}")
        
        return compiled_keywords
    
    def _match_keywords(self, text: str) -> tuple[List[str], float]:
        """匹配关键词并计算相关性分数"""
        matched_keywords = []
        relevance_score = 0.0
        
        # 权重配置
        weights = {
            'primary_keywords': 1.0,
            'secondary_keywords': 0.7,
            'competitor_keywords': 0.5
        }
        
        for category, patterns in self.keywords.items():
            weight = weights.get(category, 0.5)
            
            for pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    # 记录匹配的关键词
                    keyword = pattern.pattern.replace(r'\b', '').replace('\\', '')
                    matched_keywords.append(keyword)
                    
                    # 计算相关性分数（考虑匹配次数）
                    relevance_score += len(matches) * weight
        
        # 标准化分数到 0-1 范围
        max_possible_score = len(self.keywords['primary_keywords']) * 1.0
        if max_possible_score > 0:
            relevance_score = min(relevance_score / max_possible_score, 1.0)
        
        return list(set(matched_keywords)), relevance_score
    
    def _is_relevant(self, post_title: str, post_content: str) -> tuple[bool, List[str], float]:
        """判断帖子是否相关"""
        # 合并标题和内容进行关键词匹配
        full_text = f"{post_title} {post_content}"
        matched_keywords, relevance_score = self._match_keywords(full_text)
        
        # 判断是否超过相关性阈值
        is_relevant = (
            relevance_score >= monitoring_config.relevance_threshold and 
            len(matched_keywords) > 0
        )
        
        return is_relevant, matched_keywords, relevance_score
    
    def _extract_post_data(self, submission) -> Optional[RedditPost]:
        """提取帖子数据"""
        try:
            # 获取帖子内容
            title = submission.title
            selftext = getattr(submission, 'selftext', '') or ''
            
            # 检查相关性
            is_relevant, matched_keywords, relevance_score = self._is_relevant(title, selftext)
            
            if not is_relevant:
                return None
            
            # 创建帖子对象
            post = RedditPost(
                id=submission.id,
                title=title,
                content=selftext[:1000] if selftext else title,  # 限制内容长度
                subreddit=submission.subreddit.display_name,
                author=str(submission.author) if submission.author else '[deleted]',
                created_time=datetime.fromtimestamp(submission.created_utc),
                score=submission.score,
                num_comments=submission.num_comments,
                url=submission.url,
                permalink=f"https://reddit.com{submission.permalink}",
                upvote_ratio=submission.upvote_ratio,
                is_self=submission.is_self,
                selftext=selftext,
                keywords_matched=matched_keywords,
                relevance_score=relevance_score
            )
            
            # 暂存 submission 对象以便后续提取评论
            post._submission = submission
            
            # 计算影响力评分
            post.influence_score = self._calculate_basic_influence(post)
            
            # 获取作者 karma
            author_karma = cache_manager.get_user_karma(post.author) or 0
            post.author_karma = author_karma
            
            # 获取帖子作者信息
            if post.author and post.author != '[deleted]':
                author_info = self.get_user_info(post.author)
                if author_info:
                    post.author_info = author_info
                    post.author_kol_score = author_info.get('kol_score', 0.0)
            
            return post
            
        except Exception as e:
            self.logger.error(f"提取帖子数据失败 {submission.id}: {e}")
            return None
    
    def _extract_comments(self, submission, max_comments: int = 20) -> List[RedditComment]:
        """提取评论数据（支持嵌套结构）"""
        comments = []
        
        try:
            # 展开所有评论
            submission.comments.replace_more(limit=0)
            
            # 第一步：收集所有相关评论到平坦列表
            flat_comments = []
            comment_count = 0
            
            for comment in submission.comments.list():
                if comment_count >= max_comments:
                    break
                
                try:
                    if hasattr(comment, 'body') and comment.body != '[deleted]':
                        # 检查评论是否包含相关关键词
                        matched_keywords, relevance_score = self._match_keywords(comment.body)
                        
                        if relevance_score > 0.1:  # 评论相关性阈值较低
                            comment_obj = RedditComment(
                                id=comment.id,
                                post_id=submission.id,
                                content=comment.body,
                                author=str(comment.author) if comment.author else '[deleted]',
                                score=comment.score,
                                created_time=datetime.fromtimestamp(comment.created_utc),
                                parent_id=comment.parent_id if hasattr(comment, 'parent_id') else None,
                                depth=0  # 稍后计算
                            )
                            flat_comments.append(comment_obj)
                            comment_count += 1
                
                except Exception as e:
                    self.logger.debug(f"处理评论失败: {e}")
                    continue
            
            # 第二步：构建评论树
            if flat_comments:
                comments = self._build_comment_tree(flat_comments)
                
                # 第三步：批量获取用户信息
                self._enrich_comments_with_user_info(comments)
            
        except Exception as e:
            self.logger.warning(f"获取评论失败 {submission.id}: {e}")
        
        return comments
    
    def _build_comment_tree(self, flat_comments: List[RedditComment]) -> List[RedditComment]:
        """构建评论树结构"""
        try:
            # 创建 ID 到评论的映射
            comment_map = {comment.id: comment for comment in flat_comments}
            root_comments = []
            
            for comment in flat_comments:
                if comment.parent_id:
                    # 提取父评论 ID（移除前缀）
                    parent_id = comment.parent_id
                    if parent_id.startswith('t1_'):
                        parent_id = parent_id[3:]  # 移除 't1_' 前缀
                    elif parent_id.startswith('t3_'):
                        # 这是对帖子的直接回复
                        comment.depth = 1
                        root_comments.append(comment)
                        continue
                    
                    # 查找父评论
                    parent_comment = comment_map.get(parent_id)
                    if parent_comment:
                        comment.depth = parent_comment.depth + 1
                        # 限制最大嵌套深度
                        if comment.depth <= 3:  # 最多3层嵌套
                            parent_comment.replies.append(comment)
                        else:
                            # 超过最大深度的评论作为根评论处理
                            comment.depth = 1
                            root_comments.append(comment)
                    else:
                        # 找不到父评论，作为根评论
                        comment.depth = 1
                        root_comments.append(comment)
                else:
                    # 根级评论
                    comment.depth = 1
                    root_comments.append(comment)
            
            # 按分数排序根评论
            root_comments.sort(key=lambda x: x.score, reverse=True)
            
            return root_comments
            
        except Exception as e:
            self.logger.error(f"构建评论树失败: {e}")
            # 如果构建失败，返回平坦列表
            for comment in flat_comments:
                comment.depth = 1
            return flat_comments
    
    def _enrich_comments_with_user_info(self, comments: List[RedditComment]):
        """为评论批量获取用户信息"""
        try:
            # 收集所有需要获取信息的用户名
            usernames = set()
            self._collect_usernames_from_comments(comments, usernames)
            
            # 批量获取用户信息
            user_info_cache = {}
            
            for username in usernames:
                if username != '[deleted]':
                    user_info = self.get_user_info(username)
                    if user_info:
                        user_info_cache[username] = user_info
            
            # 将用户信息填充到评论中
            self._fill_comment_user_info(comments, user_info_cache)
            
        except Exception as e:
            self.logger.error(f"获取评论用户信息失败: {e}")
    
    def _collect_usernames_from_comments(self, comments: List[RedditComment], usernames: set):
        """递归收集所有评论中的用户名"""
        for comment in comments:
            usernames.add(comment.author)
            if comment.replies:
                self._collect_usernames_from_comments(comment.replies, usernames)
    
    def _fill_comment_user_info(self, comments: List[RedditComment], user_info_cache: Dict):
        """递归填充评论的用户信息"""
        for comment in comments:
            if comment.author in user_info_cache:
                user_info = user_info_cache[comment.author]
                comment.author_info = user_info
                comment.author_kol_score = user_info.get('kol_score', 0.0)
            
            if comment.replies:
                self._fill_comment_user_info(comment.replies, user_info_cache)
    
    def _fetch_subreddit_posts(self, subreddit_name: str, limit: int = 25) -> List[RedditPost]:
        """获取指定 subreddit 的帖子"""
        posts = []
        debug_info = {
            'total_checked': 0,
            'already_processed': 0,
            'relevant_found': 0,
            'irrelevant': 0
        }
        
        try:
            self.rate_limiter.wait_if_needed()
            self.rate_limiter.add_call()
            
            subreddit = self.reddit.subreddit(subreddit_name)
            
            # 获取热门和最新帖子
            submissions = list(subreddit.hot(limit=limit//2)) + list(subreddit.new(limit=limit//2))
            
            for submission in submissions:
                debug_info['total_checked'] += 1
                
                # 检查是否已处理过
                if cache_manager.is_post_processed(submission.id):
                    debug_info['already_processed'] += 1
                    continue
                
                # 调试信息：检查相关性
                title = submission.title
                selftext = getattr(submission, 'selftext', '') or ''
                is_relevant, matched_keywords, relevance_score = self._is_relevant(title, selftext)
                
                # 如果相关性阈值很低（调试模式），输出更多信息
                if monitoring_config.relevance_threshold <= 0.2:
                    self.logger.debug(f"📝 检查帖子: {title[:50]}...")
                    self.logger.debug(f"🔍 匹配关键词: {matched_keywords}")
                    self.logger.debug(f"📊 相关性分数: {relevance_score:.3f} (阈值: {monitoring_config.relevance_threshold})")
                    self.logger.debug(f"✅ 是否相关: {is_relevant}")
                
                # 提取帖子数据
                post = self._extract_post_data(submission)
                if post:
                    debug_info['relevant_found'] += 1
                    posts.append(post)
                    
                    # 标记为已处理
                    cache_manager.mark_post_processed(
                        submission.id, 
                        subreddit_name,
                        sentiment_score=None,  # 后续AI分析时更新
                        influence_score=self._calculate_basic_influence(post)
                    )
                else:
                    debug_info['irrelevant'] += 1
            
            # 输出调试统计
            if monitoring_config.relevance_threshold <= 0.2:
                self.logger.info(f"📊 r/{subreddit_name} 调试统计:")
                self.logger.info(f"   总检查: {debug_info['total_checked']} 个帖子")
                self.logger.info(f"   已处理: {debug_info['already_processed']} 个")
                self.logger.info(f"   找到相关: {debug_info['relevant_found']} 个")
                self.logger.info(f"   无关帖子: {debug_info['irrelevant']} 个")
            
            self.logger.info(f"从 r/{subreddit_name} 获取到 {len(posts)} 个相关帖子")
            
        except Exception as e:
            self.logger.error(f"获取 r/{subreddit_name} 帖子失败: {e}")
        
        return posts
    
    def _calculate_basic_influence(self, post: RedditPost) -> float:
        """计算基础影响力分数"""
        try:
            # 基础评分算法
            base_score = post.score * 0.4
            engagement = post.num_comments * 0.3
            
            # 获取作者 karma（如果可能）
            author_karma = cache_manager.get_user_karma(post.author) or 0
            author_factor = min(author_karma * 0.0001, 10)  # 限制最大影响
            
            # Subreddit 权重
            from config.settings import SUBREDDIT_WEIGHTS
            subreddit_weight = SUBREDDIT_WEIGHTS.get(post.subreddit, 1.0)
            
            # 相关性权重
            relevance_weight = post.relevance_score
            
            influence_score = (base_score + engagement + author_factor) * subreddit_weight * relevance_weight
            
            return round(influence_score, 2)
            
        except Exception as e:
            self.logger.error(f"计算影响力分数失败: {e}")
            return 0.0
    
    def collect_posts(self, subreddits: Optional[List[str]] = None) -> List[RedditPost]:
        """采集帖子数据"""
        if not subreddits:
            subreddits = monitoring_config.target_subreddits
        
        all_posts = []
        
        self.logger.info(f"开始采集 Reddit 数据，目标 subreddits: {subreddits}")
        
        # 使用线程池并发处理多个 subreddit
        with ThreadPoolExecutor(max_workers=3) as executor:
            future_to_subreddit = {}
            
            for subreddit in subreddits:
                if subreddit in SUBREDDIT_CONFIG:
                    max_posts = SUBREDDIT_CONFIG[subreddit]['max_posts_per_check']
                else:
                    max_posts = monitoring_config.max_posts_per_subreddit
                
                future = executor.submit(self._fetch_subreddit_posts, subreddit, max_posts)
                future_to_subreddit[future] = subreddit
            
            # 收集结果
            for future in as_completed(future_to_subreddit):
                subreddit = future_to_subreddit[future]
                try:
                    posts = future.result()
                    all_posts.extend(posts)
                except Exception as e:
                    self.logger.error(f"处理 r/{subreddit} 时出错: {e}")
        
        # 为重要帖子提取评论
        if all_posts:
            self.logger.info("开始提取重要帖子的评论...")
            
            # 筛选需要提取评论的帖子（影响力评分高或评论数多的帖子）
            important_posts = [
                post for post in all_posts 
                if (post.influence_score > 3.0 or post.num_comments > 5) and hasattr(post, '_submission')
            ]
            
            if important_posts:
                self.logger.info(f"为 {len(important_posts)} 个重要帖子提取评论...")
                
                for post in important_posts:
                    try:
                        if hasattr(post, '_submission'):
                            comments = self._extract_comments(post._submission, max_comments=50)
                            post.comments = comments
                            # 清理临时属性
                            delattr(post, '_submission')
                            
                            if comments:
                                self.logger.debug(f"帖子 {post.id} 提取到 {len(comments)} 条相关评论")
                    except Exception as e:
                        self.logger.warning(f"提取帖子 {post.id} 评论失败: {e}")
                        if hasattr(post, '_submission'):
                            delattr(post, '_submission')
            
            # 清理其他帖子的临时属性
            for post in all_posts:
                if hasattr(post, '_submission'):
                    delattr(post, '_submission')
        
        self.logger.info(f"采集完成，共获取 {len(all_posts)} 个相关帖子")
        return all_posts
    
    def collect_comments(self, post_ids: List[str]) -> Dict[str, List[RedditComment]]:
        """采集指定帖子的评论"""
        comments_by_post = {}
        
        for post_id in post_ids:
            try:
                self.rate_limiter.wait_if_needed()
                self.rate_limiter.add_call()
                
                submission = self.reddit.submission(id=post_id)
                comments = self._extract_comments(submission)
                comments_by_post[post_id] = comments
                
                self.logger.debug(f"获取帖子 {post_id} 的 {len(comments)} 条评论")
                
            except Exception as e:
                self.logger.error(f"获取帖子 {post_id} 评论失败: {e}")
                comments_by_post[post_id] = []
        
        return comments_by_post
    
    def get_user_info(self, username: str) -> Optional[Dict]:
        """获取用户详细信息"""
        try:
            # 检查缓存
            cached_info = cache_manager.get_user_detailed_info(username)
            if cached_info is not None:
                return cached_info
            
            self.rate_limiter.wait_if_needed()
            self.rate_limiter.add_call()
            
            user = self.reddit.redditor(username)
            
            # 基础信息
            user_info = {
                'username': username,
                'total_karma': user.link_karma + user.comment_karma,
                'link_karma': user.link_karma,
                'comment_karma': user.comment_karma,
                'account_created': datetime.fromtimestamp(user.created_utc),
                'verified': getattr(user, 'verified', False),
                'is_gold': getattr(user, 'is_gold', False),
                'is_mod': getattr(user, 'is_mod', False),
            }
            
            # 计算账户年龄
            account_age = (datetime.now() - user_info['account_created']).days
            user_info['account_age_days'] = account_age
            
            # 获取最近发帖活动分析
            try:
                # 分析最近的帖子和评论来判断专业领域
                recent_posts = list(user.submissions.new(limit=10))
                recent_comments = list(user.comments.new(limit=20))
                
                # 统计发帖的 subreddit 分布
                subreddit_activity = {}
                total_posts = len(recent_posts)
                total_comments = len(recent_comments)
                
                for post in recent_posts:
                    subreddit = str(post.subreddit).lower()
                    subreddit_activity[subreddit] = subreddit_activity.get(subreddit, 0) + 1
                
                for comment in recent_comments:
                    subreddit = str(comment.subreddit).lower()
                    subreddit_activity[subreddit] = subreddit_activity.get(subreddit, 0) + 1
                
                # 计算平均分数
                avg_post_score = sum(post.score for post in recent_posts) / max(total_posts, 1)
                avg_comment_score = sum(comment.score for comment in recent_comments) / max(total_comments, 1)
                
                user_info.update({
                    'recent_posts_count': total_posts,
                    'recent_comments_count': total_comments,
                    'avg_post_score': round(avg_post_score, 2),
                    'avg_comment_score': round(avg_comment_score, 2),
                    'active_subreddits': list(subreddit_activity.keys())[:5],  # 最活跃的5个
                    'subreddit_activity': subreddit_activity
                })
                
                # 检查是否在技术相关 subreddit 活跃（KOL 分析）
                tech_subreddits = {
                    'networking', 'cisco', 'mikrotik', 'homelab', 'sysadmin', 
                    'networking_engineers', 'ccna', 'ccnp', 'ccie', 'juniper',
                    'technology', 'techsupport', 'it', 'enterprise'
                }
                
                tech_activity = sum(subreddit_activity.get(sub, 0) for sub in tech_subreddits)
                user_info['tech_focus_score'] = tech_activity / max(total_posts + total_comments, 1)
                
            except Exception as e:
                self.logger.debug(f"获取用户活动信息失败 {username}: {e}")
                user_info.update({
                    'recent_posts_count': 0,
                    'recent_comments_count': 0,
                    'avg_post_score': 0,
                    'avg_comment_score': 0,
                    'active_subreddits': [],
                    'tech_focus_score': 0
                })
            
            # 计算 KOL 评分
            kol_score = self._calculate_kol_score(user_info)
            user_info['kol_score'] = kol_score
            
            # 缓存用户信息（24小时有效）
            cache_manager.cache_user_detailed_info(username, user_info)
            
            return user_info
            
        except Exception as e:
            self.logger.debug(f"获取用户信息失败 {username}: {e}")
            return None
    
    def _calculate_kol_score(self, user_info: Dict) -> float:
        """计算用户 KOL 评分"""
        try:
            score = 0.0
            
            # Karma 评分 (0-30分)
            total_karma = user_info.get('total_karma', 0)
            karma_score = min(total_karma / 1000, 30)  # 每1000 karma得1分，最高30分
            
            # 账户年龄评分 (0-10分)
            account_age = user_info.get('account_age_days', 0)
            age_score = min(account_age / 365 * 2, 10)  # 每年2分，最高10分
            
            # 活跃度评分 (0-20分)
            recent_activity = user_info.get('recent_posts_count', 0) + user_info.get('recent_comments_count', 0)
            activity_score = min(recent_activity * 0.5, 20)  # 每个活动0.5分，最高20分
            
            # 内容质量评分 (0-20分)
            avg_post_score = user_info.get('avg_post_score', 0)
            avg_comment_score = user_info.get('avg_comment_score', 0)
            quality_score = min((avg_post_score + avg_comment_score) / 2, 20)
            
            # 专业领域评分 (0-20分)
            tech_focus = user_info.get('tech_focus_score', 0)
            tech_score = tech_focus * 20
            
            # 特殊身份加分
            special_bonus = 0
            if user_info.get('verified'): special_bonus += 5
            if user_info.get('is_gold'): special_bonus += 3
            if user_info.get('is_mod'): special_bonus += 5
            
            total_score = karma_score + age_score + activity_score + quality_score + tech_score + special_bonus
            
            return round(min(total_score, 100), 2)  # 最高100分
            
        except Exception as e:
            self.logger.error(f"计算 KOL 评分失败: {e}")
            return 0.0
    
    def health_check(self) -> Dict[str, any]:
        """健康检查"""
        try:
            # 测试 Reddit API 连接
            self.rate_limiter.wait_if_needed()
            self.rate_limiter.add_call()
            
            test_subreddit = self.reddit.subreddit('test')
            list(test_subreddit.hot(limit=1))
            
            # 获取速率限制状态
            used_calls = len([call for call in self.rate_limiter.calls 
                            if time.time() - call < self.rate_limiter.period])
            
            return {
                'status': 'healthy',
                'reddit_api': 'connected',
                'rate_limit_used': f"{used_calls}/{self.rate_limiter.max_calls}",
                'keywords_compiled': sum(len(patterns) for patterns in self.keywords.values()),
                'target_subreddits': len(monitoring_config.target_subreddits)
            }
            
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e)
            }

# 使用示例
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Reddit 数据采集器')
    parser.add_argument('--manual', action='store_true', help='手动运行一次采集')
    parser.add_argument('--subreddit', type=str, help='指定 subreddit')
    parser.add_argument('--health', action='store_true', help='健康检查')
    
    args = parser.parse_args()
    
    collector = RedditCollector()
    
    if args.health:
        health = collector.health_check()
        print(f"健康状态: {health}")
    elif args.manual:
        subreddits = [args.subreddit] if args.subreddit else None
        posts = collector.collect_posts(subreddits)
        print(f"采集到 {len(posts)} 个帖子")
        for post in posts[:3]:  # 显示前3个
            print(f"- {post.title} (分数: {post.score}, 相关性: {post.relevance_score:.2f})")
    else:
        print("请使用 --manual 或 --health 参数") 