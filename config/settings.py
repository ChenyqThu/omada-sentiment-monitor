"""
Omada 舆情监控系统配置文件
"""
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv
from pathlib import Path

# 清理环境变量，确保只从 .env 文件读取
def clear_and_load_env():
    """清理环境变量并从 .env 文件重新加载"""
    # 需要清理的环境变量前缀
    prefixes_to_clear = [
        'REDDIT_', 'AZURE_', 'OPENAI_', 'NOTION_', 'SMTP_', 'EMAIL_',
        'TARGET_', 'PRIMARY_', 'SECONDARY_', 'COMPETITOR_', 'CHECK_',
        'MAX_', 'RELEVANCE_', 'ALERTS_', 'CRITICAL_', 'HIGH_',
        'INFLUENCE_', 'NEGATIVE_', 'LOG_', 'DEBUG_', 'TEST_',
        'DATA_', 'CACHE_', 'AI_', 'ENABLE_', 'YOUTUBE_'
    ]
    
    # 清理现有环境变量
    keys_to_remove = []
    for key in os.environ:
        for prefix in prefixes_to_clear:
            if key.startswith(prefix):
                keys_to_remove.append(key)
                break
    
    for key in keys_to_remove:
        os.environ.pop(key, None)
    
    # 从 .env 文件重新加载
    env_path = Path('.env')
    if env_path.exists():
        load_dotenv(env_path, override=True)
        print(f"✅ 从 {env_path.absolute()} 加载配置")
        return True
    else:
        print(f"❌ 未找到 .env 文件: {env_path.absolute()}")
        return False

# 加载环境变量
env_loaded = clear_and_load_env()

def get_env_var(key: str, default: str = '', required: bool = False) -> str:
    """安全获取环境变量"""
    value = os.getenv(key, default).strip()
    if required and not value:
        raise ValueError(f"必需的环境变量 {key} 未设置")
    return value

def get_env_int(key: str, default: int = 0) -> int:
    """获取整数环境变量"""
    try:
        return int(get_env_var(key, str(default)))
    except ValueError:
        return default

def get_env_float(key: str, default: float = 0.0) -> float:
    """获取浮点数环境变量"""
    try:
        return float(get_env_var(key, str(default)))
    except ValueError:
        return default

def get_env_bool(key: str, default: bool = False) -> bool:
    """获取布尔值环境变量"""
    value = get_env_var(key, str(default).lower()).lower()
    return value in ('true', '1', 'yes', 'on')

def get_env_list(key: str, default: List[str] = None, separator: str = ',') -> List[str]:
    """获取列表环境变量"""
    if default is None:
        default = []
    value = get_env_var(key, separator.join(default))
    return [item.strip() for item in value.split(separator) if item.strip()]

@dataclass
class RedditConfig:
    """Reddit API 配置"""
    client_id: str = ''
    client_secret: str = ''
    user_agent: str = 'omada-sentiment-monitor:v1.0.0'
    rate_limit_calls: int = 100
    rate_limit_period: int = 60
    
    def __post_init__(self):
        self.client_id = get_env_var('REDDIT_CLIENT_ID', required=True)
        self.client_secret = get_env_var('REDDIT_CLIENT_SECRET', required=True)
        self.user_agent = get_env_var('REDDIT_USER_AGENT', self.user_agent)
        self.rate_limit_calls = get_env_int('REDDIT_RATE_LIMIT_CALLS', self.rate_limit_calls)
        self.rate_limit_period = get_env_int('REDDIT_RATE_LIMIT_PERIOD', self.rate_limit_period)

@dataclass
class NotionConfig:
    """Notion API 配置"""
    token: str = ''
    database_id: str = ''
    api_version: str = '2022-06-28'
    max_retries: int = 3
    timeout: int = 30
    enabled: bool = False
    required: bool = False
    
    kol_database_id: str = ''
    youtube_database_id: str = ''

    def __post_init__(self):
        self.token = get_env_var('NOTION_TOKEN', required=True)
        self.database_id = get_env_var('NOTION_DATABASE_ID', required=True)
        self.api_version = get_env_var('NOTION_API_VERSION', self.api_version)
        self.max_retries = get_env_int('NOTION_MAX_RETRIES', self.max_retries)
        self.timeout = get_env_int('NOTION_TIMEOUT', self.timeout)
        self.enabled = bool(self.token and self.database_id)
        self.required = get_env_bool('NOTION_REQUIRED', self.required)
        self.kol_database_id = get_env_var('NOTION_KOL_DATABASE_ID', self.kol_database_id)
        self.youtube_database_id = get_env_var('NOTION_YOUTUBE_DATABASE_ID', self.youtube_database_id)

@dataclass
class EmailConfig:
    """邮件配置"""
    smtp_host: str = 'smtp.gmail.com'
    smtp_port: int = 587
    username: str = ''
    password: str = ''
    use_tls: bool = True
    recipients: List[str] = None
    
    def __post_init__(self):
        self.smtp_host = get_env_var('SMTP_HOST', self.smtp_host)
        self.smtp_port = get_env_int('SMTP_PORT', self.smtp_port)
        self.username = get_env_var('SMTP_USERNAME')
        self.password = get_env_var('SMTP_PASSWORD')
        self.use_tls = get_env_bool('SMTP_USE_TLS', self.use_tls)
        self.recipients = get_env_list('EMAIL_RECIPIENTS', [])

@dataclass
class MonitoringConfig:
    """监控配置"""
    target_subreddits: List[str] = None
    primary_keywords: List[str] = None
    secondary_keywords: List[str] = None
    competitor_keywords: List[str] = None
    check_interval: int = 300
    max_posts_per_subreddit: int = 25
    relevance_threshold: float = 0.3
    collector_type: str = 'json'  # 'json' or 'praw'

    def __post_init__(self):
        self.target_subreddits = get_env_list('TARGET_SUBREDDITS',
            ['homenetworking', 'networking', 'sysadmin', 'TPLINK'])
        self.primary_keywords = get_env_list('PRIMARY_KEYWORDS',
            ['omada', 'tp-link', 'tplink', 'access point', 'archer', 'deco', 'eap'])
        self.secondary_keywords = get_env_list('SECONDARY_KEYWORDS',
            ['wifi', 'wireless', 'router', 'switch'])
        self.competitor_keywords = get_env_list('COMPETITOR_KEYWORDS',
            ['ubiquiti', 'unifi', 'cisco', 'netgear'])
        self.check_interval = get_env_int('CHECK_INTERVAL', self.check_interval)
        self.max_posts_per_subreddit = get_env_int('MAX_POSTS_PER_SUBREDDIT', self.max_posts_per_subreddit)
        self.relevance_threshold = get_env_float('RELEVANCE_THRESHOLD', self.relevance_threshold)
        self.collector_type = get_env_var('COLLECTOR_TYPE', self.collector_type)

@dataclass
class SystemConfig:
    """系统配置"""
    log_level: str = 'INFO'
    debug_mode: bool = False
    test_mode: bool = False
    data_retention_days: int = 30
    def __post_init__(self):
        self.log_level = get_env_var('LOG_LEVEL', self.log_level)
        self.debug_mode = get_env_bool('DEBUG_MODE', self.debug_mode)
        self.test_mode = get_env_bool('TEST_MODE', self.test_mode)
        self.data_retention_days = get_env_int('DATA_RETENTION_DAYS', self.data_retention_days)

@dataclass
class AIFilterConfig:
    """AI 批量过滤配置"""
    provider: str = 'gemini'  # 'gemini' or 'openai'
    api_key: str = ''
    model: str = 'gemini-2.0-flash-lite'
    base_url: str = ''  # for OpenAI-compatible providers
    relevance_threshold: float = 0.4
    batch_size: int = 15
    db_path: str = 'data/omada_monitor.db'

    def __post_init__(self):
        self.provider = get_env_var('AI_FILTER_PROVIDER', self.provider)
        self.api_key = get_env_var('AI_FILTER_API_KEY', self.api_key)
        self.model = get_env_var('AI_FILTER_MODEL', self.model)
        self.base_url = get_env_var('AI_FILTER_BASE_URL', self.base_url)
        self.relevance_threshold = get_env_float('AI_FILTER_RELEVANCE_THRESHOLD', self.relevance_threshold)
        self.batch_size = get_env_int('AI_FILTER_BATCH_SIZE', self.batch_size)
        self.db_path = get_env_var('DB_PATH', self.db_path)

@dataclass
class YouTubeConfig:
    """YouTube Data API v3 配置"""
    api_key: str = ''
    enabled: bool = False
    search_keywords: List[str] = None
    search_interval_hours: int = 4
    max_search_results: int = 10
    monitored_channels: List[str] = None
    daily_quota_limit: int = 10000
    hot_view_jump: int = 5000
    hot_like_jump: int = 200
    hot_comment_jump: int = 50

    def __post_init__(self):
        self.api_key = get_env_var('YOUTUBE_API_KEY', self.api_key)
        self.enabled = get_env_bool('YOUTUBE_ENABLED', self.enabled)
        self.search_keywords = get_env_list(
            'YOUTUBE_SEARCH_KEYWORDS',
            ['TP-Link Omada', 'Omada SDN', 'Omada EAP', 'Omada', 'Unifi', 'Ubiquiti'],
        )
        self.search_interval_hours = get_env_int('YOUTUBE_SEARCH_INTERVAL_HOURS', self.search_interval_hours)
        self.max_search_results = get_env_int('YOUTUBE_MAX_SEARCH_RESULTS', self.max_search_results)
        self.monitored_channels = get_env_list(
            'YOUTUBE_MONITORED_CHANNELS',
            ['@UbiquitiInc', '@UniFi-Academy', '@SPXLabs', '@WillieHowe', '@CrosstalkSolutions', '@landpet'],
        )
        self.daily_quota_limit = get_env_int('YOUTUBE_DAILY_QUOTA_LIMIT', self.daily_quota_limit)
        self.hot_view_jump = get_env_int('YOUTUBE_HOT_VIEW_JUMP', self.hot_view_jump)
        self.hot_like_jump = get_env_int('YOUTUBE_HOT_LIKE_JUMP', self.hot_like_jump)
        self.hot_comment_jump = get_env_int('YOUTUBE_HOT_COMMENT_JUMP', self.hot_comment_jump)

# 全局配置实例 - 延迟初始化
reddit_config: Optional[RedditConfig] = None
notion_config: Optional[NotionConfig] = None
email_config: Optional[EmailConfig] = None
monitoring_config: Optional[MonitoringConfig] = None
system_config: Optional[SystemConfig] = None
ai_filter_config: Optional[AIFilterConfig] = None
youtube_config: Optional[YouTubeConfig] = None

def initialize_configs():
    """初始化所有配置"""
    global reddit_config, notion_config, email_config
    global monitoring_config, system_config, ai_filter_config
    global youtube_config

    try:
        reddit_config = RedditConfig()
        notion_config = NotionConfig()
        email_config = EmailConfig()
        monitoring_config = MonitoringConfig()
        system_config = SystemConfig()
        ai_filter_config = AIFilterConfig()
        youtube_config = YouTubeConfig()

        print("✅ 所有配置初始化完成")
        if youtube_config.enabled:
            print(f"  📺 YouTube 监控已启用 ({len(youtube_config.search_keywords)} 关键词, "
                  f"{len(youtube_config.monitored_channels)} 频道)")
        return True
    except Exception as e:
        print(f"❌ 配置初始化失败: {e}")
        return False

# 自动初始化配置
if env_loaded:
    initialize_configs()