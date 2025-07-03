"""
Notion API 客户端
负责将 Reddit 数据和 AI 分析结果同步到 Notion Database
支持将帖子内容写入页面正文
"""
import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Union

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import notion_config
from src.utils.logger import LoggerMixin
from src.collectors.reddit_collector import RedditPost, RedditComment
from src.analyzers.base_analyzer import AnalysisResult

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
    
    def _format_property_value(self, property_name: str, value: Any) -> Dict[str, Any]:
        """格式化属性值为 Notion API 格式"""
        schema = self._get_database_schema()
        prop_config = schema.get(property_name, {})
        prop_type = prop_config.get('type', 'rich_text')
        
        if value is None:
            return None
        
        try:
            if prop_type == 'title':
                return {
                    'title': [{'text': {'content': str(value)[:2000]}}]  # Notion 标题限制
                }
            elif prop_type == 'rich_text':
                return {
                    'rich_text': [{'text': {'content': str(value)[:2000]}}]  # Notion 文本限制
                }
            elif prop_type == 'number':
                return {
                    'number': float(value) if value is not None else None
                }
            elif prop_type == 'select':
                return {
                    'select': {'name': str(value)} if value else None
                }
            elif prop_type == 'multi_select':
                if isinstance(value, (list, tuple)):
                    return {
                        'multi_select': [{'name': str(v)} for v in value if v]
                    }
                elif isinstance(value, str):
                    # 如果是逗号分隔的字符串
                    items = [item.strip() for item in value.split(',') if item.strip()]
                    return {
                        'multi_select': [{'name': item} for item in items]
                    }
                else:
                    return {
                        'multi_select': [{'name': str(value)}] if value else []
                    }
            elif prop_type == 'checkbox':
                return {
                    'checkbox': bool(value)
                }
            elif prop_type == 'date':
                if isinstance(value, datetime):
                    return {
                        'date': {'start': value.isoformat()}
                    }
                elif isinstance(value, str):
                    return {
                        'date': {'start': value}
                    }
                else:
                    return None
            elif prop_type == 'url':
                return {
                    'url': str(value) if value else None
                }
            else:
                # 默认当作文本处理
                return {
                    'rich_text': [{'text': {'content': str(value)[:2000]}}]
                }
        
        except Exception as e:
            self.logger.warning(f"格式化属性 {property_name} 失败: {e}，使用默认格式")
            return {
                'rich_text': [{'text': {'content': str(value)[:2000]}}]
            }
    
    def _create_page_properties(self, post: RedditPost, analysis: Optional[AnalysisResult] = None) -> Dict[str, Any]:
        """创建页面属性"""
        properties = {}
        
        # 基础信息
        property_mappings = {
            '标题': post.title,
            '内容': post.content[:500] + '...' if len(post.content) > 500 else post.content,  # 属性中只存摘要
            '类型': 'Post',
            '来源': 'Reddit',
            'Reddit ID': post.id,  # 添加 Reddit ID 用于唯一标识
            'Subreddit': f'r/{post.subreddit}',
            '作者': post.author,
            '分数': post.score,
            '评论数': post.num_comments,
            '发布时间': post.created_time,
            '采集时间': datetime.now(timezone.utc),
            '最后更新时间': datetime.now(timezone.utc),  # 添加最后更新时间
            'Reddit链接': post.url,
            '影响力评分': post.influence_score,
            '用户Karma': post.author_karma,
            '相关性得分': post.relevance_score,
            '匹配关键词': post.keywords_matched,
        }
        
        # 添加 AI 分析结果
        if analysis and not analysis.error:
            if analysis.sentiment:
                sentiment_map = {'positive': '正面', 'negative': '负面', 'neutral': '中性'}
                property_mappings.update({
                    '情感倾向': sentiment_map.get(analysis.sentiment.sentiment, '中性'),
                    '情感分数': analysis.sentiment.score,
                    '置信度': analysis.sentiment.confidence,
                })
            
            if analysis.key_phrases and analysis.key_phrases.phrases:
                property_mappings['关键词'] = analysis.key_phrases.phrases[:10]  # 限制数量
            
            if analysis.topics and analysis.topics.topics:
                property_mappings['主题分类'] = analysis.topics.topics
            
            if analysis.summary:
                property_mappings['AI摘要'] = analysis.summary
            
            # 分析器类型
            from config.settings import ai_analysis_config
            property_mappings['分析器类型'] = ai_analysis_config.analyzer_type
        
        # 设置优先级
        priority = '低'
        if post.influence_score > 8:
            priority = '高'
        elif post.influence_score > 5:
            priority = '中'
        property_mappings['优先级'] = priority
        
        # 格式化所有属性
        for prop_name, value in property_mappings.items():
            formatted_value = self._format_property_value(prop_name, value)
            if formatted_value is not None:
                properties[prop_name] = formatted_value
        
        return properties
    
    def _create_page_content(self, post: RedditPost) -> List[Dict[str, Any]]:
        """创建页面内容"""
        try:
            blocks = []
            
            # 帖子信息部分
            blocks.append({
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": "📋 帖子信息"}
                    }]
                }
            })
            
            # 作者信息（如果有详细信息）
            author_info_text = f"作者: {post.author}"
            if hasattr(post, 'author_info') and post.author_info:
                kol_score = post.author_kol_score
                total_karma = post.author_info.get('total_karma', 0)
                account_age = post.author_info.get('account_age_days', 0)
                
                # 添加 KOL 标识
                kol_indicator = ""
                if kol_score >= 70:
                    kol_indicator = " 🌟 高影响力KOL"
                elif kol_score >= 50:
                    kol_indicator = " ⭐ 中等影响力KOL"
                elif kol_score >= 30:
                    kol_indicator = " 📈 潜在KOL"
                
                author_info_text = f"作者: {post.author}{kol_indicator} (KOL评分: {kol_score}, Karma: {total_karma:,}, 账户年龄: {account_age//365}年{account_age%365}天)"
            
            blocks.append({
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": author_info_text}
                    }]
                }
            })
            
            blocks.append({
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": f"发布时间: {post.created_time.strftime('%Y-%m-%d %H:%M:%S')}"}
                    }]
                }
            })
            
            blocks.append({
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": f"分数: {post.score} | 评论数: {post.num_comments} | 赞同率: {post.upvote_ratio:.1%}"}
                    }]
                }
            })
            
            # 帖子内容部分
            blocks.append({
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{
                        "type": "text",
                        "text": {"content": "📝 帖子内容"}
                    }]
                }
            })
            
            # 使用完整的帖子内容（selftext 优先）
            full_content = post.selftext if post.selftext and post.selftext.strip() else post.content
            
            if full_content and full_content.strip():
                content_chunks = self._split_text(full_content, 2000)
                for chunk in content_chunks:
                    blocks.append({
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": chunk.strip()}
                            }]
                        }
                    })
            else:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": "（仅标题帖子，无正文内容）"}
                        }]
                    }
                })
            
            # 评论部分
            if post.comments and len(post.comments) > 0:
                blocks.append({
                    "type": "heading_2",
                    "heading_2": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": f"💬 评论 ({len(self._count_all_comments(post.comments))} 条)"}
                        }]
                    }
                })
                
                # 递归添加嵌套评论
                try:
                    comment_blocks = self._create_comment_blocks(post.comments)
                    blocks.extend(comment_blocks)
                    
                except Exception as comment_error:
                    self.logger.error(f"处理评论时发生错误: {comment_error}")
                    # 添加错误说明
                    blocks.append({
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": "⚠️ 评论加载失败，请稍后重试"}
                            }]
                        }
                    })
            
            # 验证所有块的结构
            validated_blocks = []
            for i, block in enumerate(blocks):
                if self._validate_block_structure(block, i):
                    validated_blocks.append(block)
                else:
                    self.logger.warning(f"块 {i} 验证失败，跳过: {block.get('type', 'unknown')}")
            
            self.logger.debug(f"创建了 {len(validated_blocks)} 个有效内容块")
            return validated_blocks
            
        except Exception as e:
            self.logger.error(f"创建页面内容失败: {e}")
            return []
    
    def _count_all_comments(self, comments: List) -> int:
        """递归计算所有评论数量（包括嵌套评论）"""
        # 类型检查，防止传入错误的参数
        if not comments:
            return 0
        
        # 如果传入的是数字，直接返回
        if isinstance(comments, (int, float)):
            return int(comments)
        
        # 如果不是列表，尝试转换
        if not isinstance(comments, (list, tuple)):
            self.logger.warning(f"_count_all_comments 接收到非列表参数: {type(comments)}")
            return 0
        
        total = 0
        for comment in comments:
            total += 1  # 当前评论
            if hasattr(comment, 'replies') and comment.replies:
                total += self._count_all_comments(comment.replies)
        return total
    
    def _create_comment_blocks(self, comments: List, depth: int = 1) -> List[Dict[str, Any]]:
        """递归创建评论块（支持嵌套显示）"""
        blocks = []
        
        for i, comment in enumerate(comments):
            try:
                # 计算缩进（用空格表示层级）
                indent = "　" * (depth - 1)  # 使用全角空格缩进
                
                # 作者信息
                author_display = comment.author
                if hasattr(comment, 'author_kol_score') and comment.author_kol_score > 0:
                    kol_score = comment.author_kol_score
                    if kol_score >= 70:
                        author_display += " 🌟"
                    elif kol_score >= 50:
                        author_display += " ⭐"
                    elif kol_score >= 30:
                        author_display += " 📈"
                    
                    # 显示详细信息
                    if hasattr(comment, 'author_info') and comment.author_info:
                        karma = comment.author_info.get('total_karma', 0)
                        tech_focus = comment.author_info.get('tech_focus_score', 0)
                        author_display += f" (KOL: {kol_score}, Karma: {karma:,}"
                        if tech_focus > 0.3:
                            author_display += f", 技术专家: {tech_focus:.1%}"
                        author_display += ")"
                
                # 评论标题
                comment_title = f"{indent}💬 {author_display} (分数: {comment.score})"
                
                blocks.append({
                    "type": "heading_3",
                    "heading_3": {
                        "rich_text": [{
                            "type": "text",
                            "text": {"content": comment_title},
                            "annotations": {"bold": depth == 1}  # 只有第一层评论加粗
                        }]
                    }
                })
                
                # 评论内容
                content_chunks = self._split_text(comment.content, 2000)
                for chunk in content_chunks:
                    # 为嵌套评论添加缩进
                    indented_content = f"{indent}{chunk.strip()}"
                    
                    blocks.append({
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": indented_content}
                            }]
                        }
                    })
                
                # 递归处理子评论
                if hasattr(comment, 'replies') and comment.replies and depth < 4:  # 限制最大深度
                    reply_blocks = self._create_comment_blocks(comment.replies, depth + 1)
                    blocks.extend(reply_blocks)
                elif hasattr(comment, 'replies') and comment.replies and depth >= 4:
                    # 超过最大深度时显示提示
                    blocks.append({
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{
                                "type": "text",
                                "text": {"content": f"{indent}　... 还有 {len(comment.replies)} 条深层回复"},
                                "annotations": {"italic": True, "color": "gray"}
                            }]
                        }
                    })
                
            except Exception as e:
                self.logger.error(f"处理评论 {i} 时发生错误: {e}")
                continue
        
        return blocks
    
    def _validate_block_structure(self, block: Dict[str, Any], index: int) -> bool:
        """验证块结构是否正确"""
        try:
            # 检查基本结构
            if not isinstance(block, dict):
                self.logger.warning(f"块 {index} 不是字典类型")
                return False
            
            # 检查必需字段
            if 'type' not in block:
                self.logger.warning(f"块 {index} 缺少 type 字段")
                return False
            
            block_type = block['type']
            
            # 检查对应的内容字段是否存在
            if block_type not in block:
                self.logger.warning(f"块 {index} 类型为 {block_type}，但缺少对应的内容字段")
                return False
            
            # 检查文本块的 rich_text 结构
            if block_type in ['paragraph', 'heading_1', 'heading_2', 'heading_3']:
                content = block[block_type]
                if not isinstance(content, dict) or 'rich_text' not in content:
                    self.logger.warning(f"块 {index} ({block_type}) 缺少 rich_text 字段")
                    return False
                
                rich_text = content['rich_text']
                if not isinstance(rich_text, list) or len(rich_text) == 0:
                    self.logger.warning(f"块 {index} ({block_type}) rich_text 不是有效的列表")
                    return False
                
                # 检查每个 rich_text 项目
                for j, item in enumerate(rich_text):
                    if not isinstance(item, dict) or 'text' not in item:
                        self.logger.warning(f"块 {index} ({block_type}) rich_text[{j}] 缺少 text 字段")
                        return False
                    
                    text_obj = item['text']
                    if not isinstance(text_obj, dict) or 'content' not in text_obj:
                        self.logger.warning(f"块 {index} ({block_type}) rich_text[{j}].text 缺少 content 字段")
                        return False
                    
                    # 确保内容不为空
                    content_text = text_obj['content']
                    if not isinstance(content_text, str) or not content_text.strip():
                        self.logger.warning(f"块 {index} ({block_type}) rich_text[{j}] 内容为空")
                        return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"验证块 {index} 结构时出错: {e}")
            return False
    
    def _split_text(self, text: str, max_length: int = 2000) -> List[str]:
        """分割长文本"""
        if len(text) <= max_length:
            return [text]
        
        chunks = []
        current_pos = 0
        
        while current_pos < len(text):
            end_pos = current_pos + max_length
            
            if end_pos >= len(text):
                chunks.append(text[current_pos:])
                break
            
            # 尝试在单词边界分割
            split_pos = text.rfind(' ', current_pos, end_pos)
            if split_pos == -1 or split_pos <= current_pos:
                split_pos = end_pos
            
            chunks.append(text[current_pos:split_pos])
            current_pos = split_pos + 1 if split_pos < len(text) else split_pos
        
        return chunks
    
    def sync_post(self, post: RedditPost, analysis: Optional[AnalysisResult] = None) -> Optional[str]:
        """同步单个帖子到 Notion"""
        try:
            # 检查是否已存在
            existing_page = self._find_existing_page(post.id)
            
            if existing_page:
                # 检查是否需要更新
                update_info = self._should_update_post(existing_page, post)
                
                if update_info['should_update'] or update_info['should_update_content']:
                    page_id = existing_page['id']
                    if self.update_existing_page(page_id, post, update_info, analysis):
                        self.logger.info(f"帖子 {post.id} 更新成功")
                        return page_id
                    else:
                        self.logger.error(f"帖子 {post.id} 更新失败")
                        return None
                else:
                    self.logger.debug(f"帖子 {post.id} 无需更新: {update_info['reason']}")
                    return existing_page['id']
            
            # 如果不存在，创建新页面
            # 创建页面属性
            properties = self._create_page_properties(post, analysis)
            
            # 创建页面
            response = self.client.pages.create(
                parent={'database_id': self.database_id},
                properties=properties
            )
            
            page_id = response['id']
            self.logger.info(f"创建页面成功: {page_id}")
            
            # 添加页面内容
            try:
                content_blocks = self._create_page_content(post)
                if content_blocks:
                    self.client.blocks.children.append(
                        block_id=page_id,
                        children=content_blocks
                    )
                    self.logger.debug(f"页面内容添加成功: {len(content_blocks)} 个块")
            except Exception as e:
                self.logger.warning(f"添加页面内容失败: {e}")
            
            return page_id
            
        except APIResponseError as e:
            self.logger.error(f"Notion API 错误: {e}")
            return None
        except Exception as e:
            self.logger.error(f"同步帖子失败: {e}")
            return None
    
    def _find_existing_page(self, reddit_id: str) -> Optional[Dict[str, Any]]:
        """查找是否已存在相同的帖子"""
        try:
            # 通过 Reddit ID 查找已存在的页面
            response = self.client.databases.query(
                database_id=self.database_id,
                filter={
                    "property": "Reddit ID",
                    "rich_text": {
                        "equals": reddit_id
                    }
                },
                page_size=1
            )
            
            results = response.get('results', [])
            if results:
                self.logger.debug(f"找到已存在的帖子: {reddit_id}")
                return results[0]
            
            return None
            
        except Exception as e:
            self.logger.warning(f"查找已存在页面失败: {e}")
            return None
    
    def sync_posts_batch(self, posts: List[RedditPost], analyses: Optional[List[AnalysisResult]] = None) -> Dict[str, Any]:
        """批量同步帖子"""
        results = {
            'success_count': 0,
            'failed_count': 0,
            'updated_count': 0,  # 新增：更新计数
            'created_count': 0,  # 新增：创建计数
            'skipped_count': 0,  # 新增：跳过计数
            'page_ids': [],
            'errors': []
        }
        
        analyses = analyses or [None] * len(posts)
        
        for i, post in enumerate(posts):
            analysis = analyses[i] if i < len(analyses) else None
            
            try:
                # 检查是否已存在
                existing_page = self._find_existing_page(post.id)
                
                if existing_page:
                    # 检查是否需要更新
                    update_info = self._should_update_post(existing_page, post)
                    
                    if update_info['should_update'] or update_info['should_update_content']:
                        page_id = existing_page['id']
                        if self.update_existing_page(page_id, post, update_info, analysis):
                            results['success_count'] += 1
                            results['updated_count'] += 1
                            results['page_ids'].append(page_id)
                        else:
                            results['failed_count'] += 1
                    else:
                        results['skipped_count'] += 1
                        results['page_ids'].append(existing_page['id'])
                else:
                    # 创建新页面
                    page_id = self._create_new_page(post, analysis)
                    if page_id:
                        results['success_count'] += 1
                        results['created_count'] += 1
                        results['page_ids'].append(page_id)
                    else:
                        results['failed_count'] += 1
                        
            except Exception as e:
                results['failed_count'] += 1
                results['errors'].append(f"帖子 {post.id}: {str(e)}")
                self.logger.error(f"同步帖子 {post.id} 失败: {e}")
        
        self.logger.info(f"批量同步完成: 成功 {results['success_count']} (创建 {results['created_count']}, 更新 {results['updated_count']}, 跳过 {results['skipped_count']}), 失败 {results['failed_count']}")
        return results
    
    def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        try:
            # 测试连接
            response = self.client.databases.retrieve(database_id=self.database_id)
            
            return {
                'status': 'healthy',
                'database_title': response.get('title', [{}])[0].get('plain_text', 'Unknown'),
                'database_id': self.database_id[:8] + '...',
                'properties_count': len(response.get('properties', {}))
            }
            
        except APIResponseError as e:
            return {
                'status': 'unhealthy',
                'error': f"API错误: {e}",
                'database_id': self.database_id[:8] + '...'
            }
        except Exception as e:
            return {
                'status': 'unhealthy',
                'error': str(e),
                'database_id': self.database_id[:8] + '...'
            }
    
    def get_sync_stats(self) -> Dict[str, Any]:
        """获取同步统计"""
        try:
            response = self.client.databases.query(
                database_id=self.database_id,
                page_size=1
            )
            
            total_count = response.get('total', 0) if 'total' in response else '未知'
            
            return {
                'total_pages': total_count,
                'database_id': self.database_id[:8] + '...',
                'last_sync': datetime.now().isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"获取同步统计失败: {e}")
            return {
                'error': str(e),
                'database_id': self.database_id[:8] + '...'
            }
    
    def _should_update_post(self, existing_page: Dict[str, Any], new_post: RedditPost) -> Dict[str, Any]:
        """判断帖子是否需要更新，返回详细的更新信息"""
        try:
            # 如果禁用了更新功能，直接返回不更新
            if not notion_config.enable_update:
                return {
                    'should_update': False,
                    'should_update_content': False,
                    'reason': '更新功能已禁用'
                }
                
            properties = existing_page.get('properties', {})
            
            # 获取现有的分数和评论数
            old_score_prop = properties.get('分数', {})
            old_comments_prop = properties.get('评论数', {})
            
            old_score = 0
            old_comments = 0
            
            if old_score_prop.get('type') == 'number' and old_score_prop.get('number') is not None:
                old_score = old_score_prop['number']
            
            if old_comments_prop.get('type') == 'number' and old_comments_prop.get('number') is not None:
                old_comments = old_comments_prop['number']
            
            # 计算变化幅度
            score_change = new_post.score - old_score
            comments_change = new_post.num_comments - old_comments
            
            # 计算相对变化百分比
            score_change_percent = 0
            if old_score > 0:
                score_change_percent = abs(score_change) / old_score * 100
            elif new_post.score > 0:  # 从0分变为有分数
                score_change_percent = 100
            
            comments_change_percent = 0
            if old_comments > 0:
                comments_change_percent = abs(comments_change) / old_comments * 100
            elif new_post.num_comments > 0:  # 从0评论变为有评论
                comments_change_percent = 100
            
            # 判断是否需要更新属性
            should_update_properties = (
                # 1. 分数变化超过配置的百分比阈值且绝对变化大于最小值
                (score_change_percent > notion_config.score_change_threshold and 
                 abs(score_change) > notion_config.score_change_min) or
                # 2. 评论数变化超过配置的百分比阈值且绝对变化大于最小值
                (comments_change_percent > notion_config.comments_change_threshold and 
                 abs(comments_change) > notion_config.comments_change_min) or
                # 3. 热门帖子（分数超过阈值）且分数变化大于最小值
                (new_post.score > notion_config.hot_post_score_threshold and 
                 score_change > notion_config.hot_post_score_change_min) or
                # 4. 热议帖子（评论数超过阈值）且评论数变化大于最小值
                (new_post.num_comments > notion_config.popular_post_comments_threshold and 
                 comments_change > notion_config.popular_post_comments_change_min)
            )
            
            # 判断是否需要更新内容（主要基于评论数变化或有新评论）
            should_update_content = (
                # 评论数有显著增加
                comments_change > 0 and (
                    comments_change_percent > notion_config.comments_change_threshold or
                    comments_change >= notion_config.comments_change_min
                ) and
                # 新帖子有评论内容
                new_post.comments and len(new_post.comments) > 0
            )
            
            # 构建更新原因
            reasons = []
            if score_change_percent > notion_config.score_change_threshold and abs(score_change) > notion_config.score_change_min:
                reasons.append(f"分数变化 {score_change_percent:.1f}%")
            if comments_change_percent > notion_config.comments_change_threshold and abs(comments_change) > notion_config.comments_change_min:
                reasons.append(f"评论数变化 {comments_change_percent:.1f}%")
            if new_post.score > notion_config.hot_post_score_threshold and score_change > notion_config.hot_post_score_change_min:
                reasons.append("热门帖子分数增长")
            if new_post.num_comments > notion_config.popular_post_comments_threshold and comments_change > notion_config.popular_post_comments_change_min:
                reasons.append("热议帖子评论增长")
            if should_update_content:
                reasons.append("评论内容需要更新")
            
            result = {
                'should_update': should_update_properties,
                'should_update_content': should_update_content,
                'old_score': old_score,
                'new_score': new_post.score,
                'score_change': score_change,
                'score_change_percent': score_change_percent,
                'old_comments': old_comments,
                'new_comments': new_post.num_comments,
                'comments_change': comments_change,
                'comments_change_percent': comments_change_percent,
                'reason': '; '.join(reasons) if reasons else '无需更新'
            }
            
            if should_update_properties or should_update_content:
                self.logger.info(f"帖子 {new_post.id} 需要更新: "
                               f"分数 {old_score} -> {new_post.score} (+{score_change}, {score_change_percent:.1f}%), "
                               f"评论 {old_comments} -> {new_post.num_comments} (+{comments_change}, {comments_change_percent:.1f}%)")
                if should_update_content:
                    self.logger.info(f"帖子 {new_post.id} 需要更新页面内容（评论数变化）")
            
            return result
            
        except Exception as e:
            self.logger.error(f"检查帖子更新需求失败: {e}")
            return {
                'should_update': False,
                'should_update_content': False,
                'reason': f'检查失败: {str(e)}'
            }
    
    def update_existing_page(self, page_id: str, post: RedditPost, update_info: Dict[str, Any], analysis: Optional[AnalysisResult] = None) -> bool:
        """更新已存在的页面"""
        try:
            update_success = True
            
            # 1. 更新页面属性（如果需要）
            if update_info.get('should_update', False):
                # 创建更新的属性（只更新需要更新的字段）
                update_properties = {
                    '分数': self._format_property_value('分数', post.score),
                    '评论数': self._format_property_value('评论数', post.num_comments),
                    '影响力评分': self._format_property_value('影响力评分', post.influence_score),
                    '最后更新时间': self._format_property_value('最后更新时间', datetime.now(timezone.utc)),
                    '相关性得分': self._format_property_value('相关性得分', post.relevance_score),
                }
                
                # 如果有新的 AI 分析结果，也更新它们
                if analysis and not analysis.error:
                    if analysis.sentiment:
                        sentiment_map = {'positive': '正面', 'negative': '负面', 'neutral': '中性'}
                        update_properties.update({
                            '情感倾向': self._format_property_value('情感倾向', sentiment_map.get(analysis.sentiment.sentiment, '中性')),
                            '情感分数': self._format_property_value('情感分数', analysis.sentiment.score),
                            '置信度': self._format_property_value('置信度', analysis.sentiment.confidence),
                        })
                    
                    if analysis.key_phrases and analysis.key_phrases.phrases:
                        update_properties['关键词'] = self._format_property_value('关键词', analysis.key_phrases.phrases[:10])
                    
                    if analysis.topics and analysis.topics.topics:
                        update_properties['主题分类'] = self._format_property_value('主题分类', analysis.topics.topics)
                    
                    if analysis.summary:
                        update_properties['AI摘要'] = self._format_property_value('AI摘要', analysis.summary)
                
                # 重新计算优先级
                priority = '低'
                if post.influence_score > 8:
                    priority = '高'
                elif post.influence_score > 5:
                    priority = '中'
                update_properties['优先级'] = self._format_property_value('优先级', priority)
                
                # 过滤掉空值
                filtered_properties = {k: v for k, v in update_properties.items() if v is not None}
                
                # 更新页面属性
                self.client.pages.update(
                    page_id=page_id,
                    properties=filtered_properties
                )
                
                self.logger.info(f"页面属性更新成功: {page_id}")
            
            # 2. 更新页面内容（如果需要）
            if update_info.get('should_update_content', False):
                content_update_success = self._replace_page_content(page_id, post)
                if content_update_success:
                    self.logger.info(f"页面内容更新成功: {page_id} (评论数: {post.num_comments})")
                else:
                    self.logger.error(f"页面内容更新失败: {page_id}")
                    update_success = False
            
            return update_success
            
        except APIResponseError as e:
            self.logger.error(f"Notion API 更新错误: {e}")
            return False
        except Exception as e:
            self.logger.error(f"更新页面失败: {e}")
            return False
    
    def _create_new_page(self, post: RedditPost, analysis: Optional[AnalysisResult] = None) -> Optional[str]:
        """创建新页面"""
        try:
            # 创建页面属性
            properties = self._create_page_properties(post, analysis)
            
            # 创建页面
            response = self.client.pages.create(
                parent={'database_id': self.database_id},
                properties=properties
            )
            
            page_id = response['id']
            self.logger.info(f"创建页面成功: {page_id}")
            
            # 添加页面内容
            try:
                content_blocks = self._create_page_content(post)
                if content_blocks:
                    self.client.blocks.children.append(
                        block_id=page_id,
                        children=content_blocks
                    )
                    self.logger.debug(f"页面内容添加成功: {len(content_blocks)} 个块")
            except Exception as e:
                self.logger.warning(f"添加页面内容失败: {e}")
            
            return page_id
            
        except APIResponseError as e:
            self.logger.error(f"Notion API 错误: {e}")
            return None
        except Exception as e:
            self.logger.error(f"创建页面失败: {e}")
            return None
    
    def _replace_page_content(self, page_id: str, post: RedditPost) -> bool:
        """替换页面的所有内容（删除原有内容，重新写入）"""
        try:
            # 1. 获取页面的所有子块
            self.logger.debug(f"开始替换页面 {page_id} 的内容")
            
            # 获取现有的块
            response = self.client.blocks.children.list(block_id=page_id)
            existing_blocks = response.get('results', [])
            
            # 2. 删除所有现有的块
            if existing_blocks:
                self.logger.debug(f"删除 {len(existing_blocks)} 个现有内容块")
                for block in existing_blocks:
                    try:
                        self.client.blocks.delete(block_id=block['id'])
                    except Exception as e:
                        self.logger.warning(f"删除块 {block['id']} 失败: {e}")
            
            # 3. 添加新的内容
            new_content_blocks = self._create_page_content(post)
            if new_content_blocks:
                self.client.blocks.children.append(
                    block_id=page_id,
                    children=new_content_blocks
                )
                self.logger.debug(f"成功添加 {len(new_content_blocks)} 个新内容块")
            
            return True
            
        except APIResponseError as e:
            self.logger.error(f"Notion API 错误，替换页面内容失败: {e}")
            return False
        except Exception as e:
            self.logger.error(f"替换页面内容失败: {e}")
            return False 