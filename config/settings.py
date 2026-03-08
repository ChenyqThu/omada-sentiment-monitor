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
        'DATA_', 'CACHE_', 'AI_', 'ENABLE_'
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
class AzureConfig:
    """Azure Text Analytics 配置"""
    api_key: str = ''
    endpoint: str = ''
    api_version: str = 'v3.1'
    max_retries: int = 3
    timeout: int = 30
    
    def __post_init__(self):
        self.api_key = get_env_var('AZURE_TEXT_ANALYTICS_KEY')
        self.endpoint = get_env_var('AZURE_TEXT_ANALYTICS_ENDPOINT')
        self.api_version = get_env_var('AZURE_API_VERSION', self.api_version)
        self.max_retries = get_env_int('AZURE_MAX_RETRIES', self.max_retries)
        self.timeout = get_env_int('AZURE_TIMEOUT', self.timeout)

@dataclass
class OpenAIConfig:
    """OpenAI API 配置"""
    api_key: str = ''
    base_url: str = 'https://api.openai.com/v1'
    model: str = 'gpt-3.5-turbo'
    max_tokens: int = 150
    temperature: float = 0.3
    max_retries: int = 3
    timeout: int = 30
    
    def __post_init__(self):
        self.api_key = get_env_var('OPENAI_API_KEY')
        self.base_url = get_env_var('OPENAI_BASE_URL', self.base_url)
        self.model = get_env_var('OPENAI_MODEL', self.model)
        self.max_tokens = get_env_int('OPENAI_MAX_TOKENS', self.max_tokens)
        self.temperature = get_env_float('OPENAI_TEMPERATURE', self.temperature)
        self.max_retries = get_env_int('OPENAI_MAX_RETRIES', self.max_retries)
        self.timeout = get_env_int('OPENAI_TIMEOUT', self.timeout)

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
    
    # 更新机制配置
    enable_update: bool = True
    score_change_threshold: float = 20.0  # 分数变化百分比阈值
    score_change_min: int = 5  # 分数变化最小绝对值
    comments_change_threshold: float = 30.0  # 评论数变化百分比阈值
    comments_change_min: int = 2  # 评论数变化最小绝对值
    hot_post_score_threshold: int = 100  # 热门帖子分数阈值
    hot_post_score_change_min: int = 10  # 热门帖子分数变化最小值
    popular_post_comments_threshold: int = 50  # 热议帖子评论数阈值
    popular_post_comments_change_min: int = 5  # 热议帖子评论数变化最小值
    report_parent_page_id: str = ''
    kol_database_id: str = ''

    def __post_init__(self):
        self.token = get_env_var('NOTION_TOKEN', required=True)
        self.database_id = get_env_var('NOTION_DATABASE_ID', required=True)
        self.api_version = get_env_var('NOTION_API_VERSION', self.api_version)
        self.max_retries = get_env_int('NOTION_MAX_RETRIES', self.max_retries)
        self.timeout = get_env_int('NOTION_TIMEOUT', self.timeout)
        self.enabled = bool(self.token and self.database_id)
        self.required = get_env_bool('NOTION_REQUIRED', self.required)
        
        # 更新机制配置
        self.enable_update = get_env_bool('NOTION_ENABLE_UPDATE', self.enable_update)
        self.score_change_threshold = get_env_float('NOTION_SCORE_CHANGE_THRESHOLD', self.score_change_threshold)
        self.score_change_min = get_env_int('NOTION_SCORE_CHANGE_MIN', self.score_change_min)
        self.comments_change_threshold = get_env_float('NOTION_COMMENTS_CHANGE_THRESHOLD', self.comments_change_threshold)
        self.comments_change_min = get_env_int('NOTION_COMMENTS_CHANGE_MIN', self.comments_change_min)
        self.hot_post_score_threshold = get_env_int('NOTION_HOT_POST_SCORE_THRESHOLD', self.hot_post_score_threshold)
        self.hot_post_score_change_min = get_env_int('NOTION_HOT_POST_SCORE_CHANGE_MIN', self.hot_post_score_change_min)
        self.popular_post_comments_threshold = get_env_int('NOTION_POPULAR_POST_COMMENTS_THRESHOLD', self.popular_post_comments_threshold)
        self.popular_post_comments_change_min = get_env_int('NOTION_POPULAR_POST_COMMENTS_CHANGE_MIN', self.popular_post_comments_change_min)
        self.report_parent_page_id = get_env_var('NOTION_REPORT_PARENT_PAGE_ID', self.report_parent_page_id)
        self.kol_database_id = get_env_var('NOTION_KOL_DATABASE_ID', self.kol_database_id)

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
class AlertConfig:
    """预警配置"""
    enabled: bool = True
    critical_sentiment_threshold: float = -0.7
    high_sentiment_threshold: float = -0.5
    influence_score_threshold: int = 80
    negative_mentions_1h_threshold: int = 5
    
    def __post_init__(self):
        self.enabled = get_env_bool('ALERTS_ENABLED', self.enabled)
        self.critical_sentiment_threshold = get_env_float('CRITICAL_SENTIMENT_THRESHOLD', self.critical_sentiment_threshold)
        self.high_sentiment_threshold = get_env_float('HIGH_SENTIMENT_THRESHOLD', self.high_sentiment_threshold)
        self.influence_score_threshold = get_env_int('INFLUENCE_SCORE_THRESHOLD', self.influence_score_threshold)
        self.negative_mentions_1h_threshold = get_env_int('NEGATIVE_MENTIONS_1H_THRESHOLD', self.negative_mentions_1h_threshold)

@dataclass
class SystemConfig:
    """系统配置"""
    log_level: str = 'INFO'
    debug_mode: bool = False
    test_mode: bool = False
    data_retention_days: int = 30
    cache_enabled: bool = True
    cache_ttl: int = 3600
    
    def __post_init__(self):
        self.log_level = get_env_var('LOG_LEVEL', self.log_level)
        self.debug_mode = get_env_bool('DEBUG_MODE', self.debug_mode)
        self.test_mode = get_env_bool('TEST_MODE', self.test_mode)
        self.data_retention_days = get_env_int('DATA_RETENTION_DAYS', self.data_retention_days)
        self.cache_enabled = get_env_bool('CACHE_ENABLED', self.cache_enabled)
        self.cache_ttl = get_env_int('CACHE_TTL', self.cache_ttl)

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
class AIAnalysisConfig:
    """AI 分析配置（旧版，保留兼容）"""
    analyzer_type: str = 'local'
    enabled: bool = True
    required: bool = False
    enable_sentiment: bool = True
    enable_key_phrases: bool = True
    enable_topic_classification: bool = True
    batch_size: int = 10
    notion_sentiment_column: str = 'AI情感分析'
    notion_summary_column: str = 'AI摘要'
    notion_keywords_column: str = 'AI关键词'

    def __post_init__(self):
        self.analyzer_type = get_env_var('AI_ANALYZER_TYPE', self.analyzer_type)
        self.enabled = get_env_bool('AI_ANALYSIS_ENABLED', self.enabled)
        self.required = get_env_bool('AI_ANALYSIS_REQUIRED', self.required)
        self.enable_sentiment = get_env_bool('ENABLE_SENTIMENT_ANALYSIS', self.enable_sentiment)
        self.enable_key_phrases = get_env_bool('ENABLE_KEY_PHRASES', self.enable_key_phrases)
        self.enable_topic_classification = get_env_bool('ENABLE_TOPIC_CLASSIFICATION', self.enable_topic_classification)
        self.batch_size = get_env_int('AI_BATCH_SIZE', self.batch_size)
        self.notion_sentiment_column = get_env_var('NOTION_SENTIMENT_COLUMN', self.notion_sentiment_column)
        self.notion_summary_column = get_env_var('NOTION_SUMMARY_COLUMN', self.notion_summary_column)
        self.notion_keywords_column = get_env_var('NOTION_KEYWORDS_COLUMN', self.notion_keywords_column)

# 全局配置实例 - 延迟初始化
reddit_config: Optional[RedditConfig] = None
azure_config: Optional[AzureConfig] = None
openai_config: Optional[OpenAIConfig] = None
notion_config: Optional[NotionConfig] = None
email_config: Optional[EmailConfig] = None
monitoring_config: Optional[MonitoringConfig] = None
alert_config: Optional[AlertConfig] = None
system_config: Optional[SystemConfig] = None
ai_analysis_config: Optional[AIAnalysisConfig] = None
ai_filter_config: Optional[AIFilterConfig] = None

def initialize_configs():
    """初始化所有配置"""
    global reddit_config, azure_config, openai_config, notion_config, email_config
    global monitoring_config, alert_config, system_config, ai_analysis_config, ai_filter_config

    try:
        reddit_config = RedditConfig()
        azure_config = AzureConfig()
        openai_config = OpenAIConfig()
        notion_config = NotionConfig()
        email_config = EmailConfig()
        monitoring_config = MonitoringConfig()
        alert_config = AlertConfig()
        system_config = SystemConfig()
        ai_analysis_config = AIAnalysisConfig()
        ai_filter_config = AIFilterConfig()
        
        print("✅ 所有配置初始化完成")
        return True
    except Exception as e:
        print(f"❌ 配置初始化失败: {e}")
        return False

# Subreddit 配置映射
SUBREDDIT_CONFIG = {
    'homenetworking': {
        'priority': 'high',
        'check_interval': 300,  # 5分钟
        'max_posts_per_check': 25
    },
    'networking': {
        'priority': 'high', 
        'check_interval': 600,  # 10分钟
        'max_posts_per_check': 20
    },
    'sysadmin': {
        'priority': 'medium',
        'check_interval': 900,  # 15分钟
        'max_posts_per_check': 15
    },
    'TPLINK': {
        'priority': 'high',
        'check_interval': 300,  # 5分钟
        'max_posts_per_check': 25
    }
}

# 影响力权重配置
SUBREDDIT_WEIGHTS = {
    'homenetworking': 1.2,
    'networking': 1.0,
    'sysadmin': 0.8,
    'TPLINK': 1.5,
    'Ubiquiti': 1.0,
    'TPLink_Omada': 1.5,
    'TplinkOmada': 1.5,
    'msp': 0.8,
    'Omada_Networks': 1.5,
}

def validate_config() -> bool:
    """验证配置是否完整"""
    if not all([reddit_config, notion_config]):
        print("❌ 配置未初始化")
        return False
    
    required_configs = [
        (reddit_config.client_id, "REDDIT_CLIENT_ID"),
        (reddit_config.client_secret, "REDDIT_CLIENT_SECRET"),
        (notion_config.token, "NOTION_TOKEN"),
        (notion_config.database_id, "NOTION_DATABASE_ID"),
    ]
    
    missing_configs = []
    for value, name in required_configs:
        if not value:
            missing_configs.append(name)
    
    if missing_configs:
        print(f"❌ 缺少以下必需配置: {', '.join(missing_configs)}")
        return False
    
    print("✅ 配置验证通过")
    return True

def get_config_summary() -> Dict[str, Any]:
    """获取配置摘要（隐藏敏感信息）"""
    if not all([reddit_config, azure_config, notion_config, monitoring_config, system_config]):
        return {"error": "配置未初始化"}
    
    return {
        "reddit": {
            "client_id": reddit_config.client_id[:8] + "..." if reddit_config.client_id else "未配置",
            "rate_limit": f"{reddit_config.rate_limit_calls}/{reddit_config.rate_limit_period}s"
        },
        "azure": {
            "endpoint": azure_config.endpoint if azure_config.endpoint else "未配置",
            "api_key": azure_config.api_key[:8] + "..." if azure_config.api_key else "未配置"
        },
        "openai": {
            "api_key": openai_config.api_key[:8] + "..." if openai_config.api_key else "未配置",
            "base_url": openai_config.base_url,
            "model": openai_config.model
        },
        "notion": {
            "database_id": notion_config.database_id[:8] + "..." if notion_config.database_id else "未配置",
            "token": notion_config.token[:8] + "..." if notion_config.token else "未配置",
            "enabled": notion_config.enabled
        },
        "monitoring": {
            "subreddits": monitoring_config.target_subreddits,
            "check_interval": monitoring_config.check_interval,
            "keywords_count": len(monitoring_config.primary_keywords),
            "relevance_threshold": monitoring_config.relevance_threshold
        },
        "system": {
            "log_level": system_config.log_level,
            "debug_mode": system_config.debug_mode,
            "test_mode": system_config.test_mode
        }
    }

# 自动初始化配置
if env_loaded:
    initialize_configs() 