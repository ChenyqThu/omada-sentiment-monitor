"""
缓存管理模块
提供本地 SQLite 缓存功能
"""
import sqlite3
import json
import time
import os
import sys
from typing import Any, Optional, List, Dict
from datetime import datetime, timedelta
from dataclasses import asdict

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from config.settings import system_config
from src.utils.logger import LoggerMixin

class CacheManager(LoggerMixin):
    """缓存管理器"""
    
    def __init__(self, db_path: str = "data/cache.db"):
        self.db_path = db_path
        self.ttl = system_config.cache_ttl
        self.enabled = system_config.cache_enabled
        
        # 确保数据目录存在
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        
        # 初始化数据库
        self._init_database()
        
    def _init_database(self):
        """初始化数据库表"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 创建缓存表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS cache (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP,
                        access_count INTEGER DEFAULT 0,
                        last_accessed TIMESTAMP
                    )
                ''')
                
                # 创建已处理帖子表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS processed_posts (
                        post_id TEXT PRIMARY KEY,
                        subreddit TEXT NOT NULL,
                        processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        sentiment_score REAL,
                        influence_score REAL
                    )
                ''')
                
                # 创建用户信息缓存表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_cache (
                        username TEXT PRIMARY KEY,
                        karma INTEGER,
                        account_age_days INTEGER,
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建用户详细信息缓存表
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS user_detailed_cache (
                        username TEXT PRIMARY KEY,
                        user_info TEXT NOT NULL,  -- JSON 格式的详细信息
                        cached_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                
                # 创建索引
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_subreddit ON processed_posts(subreddit)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_posts_processed_at ON processed_posts(processed_at)')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_detailed_cached_at ON user_detailed_cache(cached_at)')
                
                conn.commit()
                self.logger.info("缓存数据库初始化完成")
                
        except Exception as e:
            self.logger.error(f"初始化缓存数据库失败: {e}")
            raise
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if not self.enabled:
            return None
            
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 查询缓存
                cursor.execute('''
                    SELECT value, expires_at FROM cache 
                    WHERE key = ? AND (expires_at IS NULL OR expires_at > ?)
                ''', (key, datetime.now().isoformat()))
                
                result = cursor.fetchone()
                if result:
                    # 更新访问统计
                    cursor.execute('''
                        UPDATE cache 
                        SET access_count = access_count + 1, last_accessed = ?
                        WHERE key = ?
                    ''', (datetime.now().isoformat(), key))
                    
                    # 解析 JSON 值
                    return json.loads(result[0])
                    
        except Exception as e:
            self.logger.error(f"获取缓存失败 {key}: {e}")
            
        return None
    
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """设置缓存值"""
        if not self.enabled:
            return False
            
        try:
            # 计算过期时间
            expires_at = None
            if ttl or self.ttl:
                expires_at = datetime.now() + timedelta(seconds=ttl or self.ttl)
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 插入或更新缓存
                cursor.execute('''
                    INSERT OR REPLACE INTO cache (key, value, expires_at, created_at, access_count)
                    VALUES (?, ?, ?, ?, 0)
                ''', (key, json.dumps(value), expires_at.isoformat() if expires_at else None, datetime.now().isoformat()))
                
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"设置缓存失败 {key}: {e}")
            return False
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache WHERE key = ?', (key,))
                conn.commit()
                return cursor.rowcount > 0
                
        except Exception as e:
            self.logger.error(f"删除缓存失败 {key}: {e}")
            return False
    
    def is_post_processed(self, post_id: str) -> bool:
        """检查帖子是否已处理"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT 1 FROM processed_posts WHERE post_id = ?', (post_id,))
                return cursor.fetchone() is not None
                
        except Exception as e:
            self.logger.error(f"检查帖子处理状态失败 {post_id}: {e}")
            return False
    
    def mark_post_processed(self, post_id: str, subreddit: str, 
                          sentiment_score: Optional[float] = None,
                          influence_score: Optional[float] = None) -> bool:
        """标记帖子为已处理"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO processed_posts 
                    (post_id, subreddit, sentiment_score, influence_score, processed_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (post_id, subreddit, sentiment_score, influence_score, datetime.now().isoformat()))
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"标记帖子处理状态失败 {post_id}: {e}")
            return False
    
    def get_user_karma(self, username: str) -> Optional[int]:
        """获取缓存的用户 karma"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查缓存是否过期（1天过期）
                cutoff_time = datetime.now() - timedelta(days=1)
                cursor.execute('''
                    SELECT karma FROM user_cache 
                    WHERE username = ? AND cached_at > ?
                ''', (username, cutoff_time.isoformat()))
                
                result = cursor.fetchone()
                return result[0] if result else None
                
        except Exception as e:
            self.logger.error(f"获取用户karma缓存失败 {username}: {e}")
            return None
    
    def cache_user_karma(self, username: str, karma: int, account_age_days: int = 0) -> bool:
        """缓存用户 karma"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO user_cache 
                    (username, karma, account_age_days, cached_at)
                    VALUES (?, ?, ?, ?)
                ''', (username, karma, account_age_days, datetime.now().isoformat()))
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"缓存用户karma失败 {username}: {e}")
            return False
    
    def cleanup_expired(self) -> int:
        """清理过期缓存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 清理过期的通用缓存
                cursor.execute('''
                    DELETE FROM cache 
                    WHERE expires_at IS NOT NULL AND expires_at <= ?
                ''', (datetime.now().isoformat(),))
                
                expired_count = cursor.rowcount
                
                # 清理旧的已处理帖子记录
                cutoff_time = datetime.now() - timedelta(days=system_config.data_retention_days)
                cursor.execute('''
                    DELETE FROM processed_posts 
                    WHERE processed_at < ?
                ''', (cutoff_time.isoformat(),))
                
                expired_count += cursor.rowcount
                
                # 清理旧的用户缓存
                user_cache_cutoff = datetime.now() - timedelta(days=7)
                cursor.execute('''
                    DELETE FROM user_cache 
                    WHERE cached_at < ?
                ''', (user_cache_cutoff.isoformat(),))
                
                expired_count += cursor.rowcount
                
                conn.commit()
                
                if expired_count > 0:
                    self.logger.info(f"清理了 {expired_count} 条过期缓存记录")
                
                return expired_count
                
        except Exception as e:
            self.logger.error(f"清理过期缓存失败: {e}")
            return 0
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 通用缓存统计
                cursor.execute('SELECT COUNT(*) FROM cache')
                cache_count = cursor.fetchone()[0]
                
                cursor.execute('SELECT COUNT(*) FROM cache WHERE expires_at <= ?', 
                             (datetime.now().isoformat(),))
                expired_cache_count = cursor.fetchone()[0]
                
                # 已处理帖子统计
                cursor.execute('SELECT COUNT(*) FROM processed_posts')
                processed_posts_count = cursor.fetchone()[0]
                
                # 用户缓存统计
                cursor.execute('SELECT COUNT(*) FROM user_cache')
                user_cache_count = cursor.fetchone()[0]
                
                # 数据库文件大小
                db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
                
                return {
                    'cache_count': cache_count,
                    'expired_cache_count': expired_cache_count,
                    'processed_posts_count': processed_posts_count,
                    'user_cache_count': user_cache_count,
                    'db_size_mb': round(db_size / 1024 / 1024, 2),
                    'enabled': self.enabled,
                    'ttl': self.ttl
                }
                
        except Exception as e:
            self.logger.error(f"获取缓存统计失败: {e}")
            return {}
    
    def clear_all(self) -> bool:
        """清空所有缓存"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM cache')
                cursor.execute('DELETE FROM processed_posts')
                cursor.execute('DELETE FROM user_cache')
                cursor.execute('DELETE FROM user_detailed_cache')
                conn.commit()
                
                self.logger.info("已清空所有缓存")
                return True
                
        except Exception as e:
            self.logger.error(f"清空缓存失败: {e}")
            return False
    
    def get_user_detailed_info(self, username: str) -> Optional[Dict]:
        """获取缓存的用户详细信息"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                
                # 检查缓存是否过期（24小时过期）
                cutoff_time = datetime.now() - timedelta(days=1)
                cursor.execute('''
                    SELECT user_info FROM user_detailed_cache 
                    WHERE username = ? AND cached_at > ?
                ''', (username, cutoff_time.isoformat()))
                
                result = cursor.fetchone()
                if result:
                    return json.loads(result[0])
                    
        except Exception as e:
            self.logger.error(f"获取用户详细信息缓存失败 {username}: {e}")
        
        return None
    
    def cache_user_detailed_info(self, username: str, user_info: Dict) -> bool:
        """缓存用户详细信息"""
        try:
            # 转换 datetime 对象为字符串
            serializable_info = {}
            for key, value in user_info.items():
                if isinstance(value, datetime):
                    serializable_info[key] = value.isoformat()
                else:
                    serializable_info[key] = value
            
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT OR REPLACE INTO user_detailed_cache 
                    (username, user_info, cached_at)
                    VALUES (?, ?, ?)
                ''', (username, json.dumps(serializable_info), datetime.now().isoformat()))
                conn.commit()
                return True
                
        except Exception as e:
            self.logger.error(f"缓存用户详细信息失败 {username}: {e}")
            return False

# 全局缓存管理器实例
cache_manager = CacheManager() 