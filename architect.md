# Omada 舆情跟踪系统 - 技术架构设计文档

## 1. 系统概述

### 1.1 架构原则
- **微服务架构**：模块化设计，便于维护和扩展
- **事件驱动**：异步处理，提高系统性能
- **容错设计**：完善的错误处理和重试机制
- **可扩展性**：支持新增数据源和分析功能

### 1.2 技术栈
```yaml
后端框架: Python 3.11+
数据采集: PRAW 7.8.1+ (Reddit API)
AI分析: Azure Text Analytics + OpenAI GPT-4
任务调度: APScheduler
数据存储: Notion API + SQLite (本地缓存)
容器化: Docker + Docker Compose
监控日志: Python logging + 自定义监控
```

## 2. 系统架构

### 2.1 整体架构图
```
┌─────────────────────────────────────────────────────────────────┐
│                        Omada 舆情监控系统                        │
├─────────────────────────────────────────────────────────────────┤
│                          用户界面层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Dashboard │  │   邮件报告   │  │   预警推送   │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
├─────────────────────────────────────────────────────────────────┤
│                          业务逻辑层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  调度管理器  │  │  预警管理器  │  │  报告生成器  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
├─────────────────────────────────────────────────────────────────┤
│                          数据处理层                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  数据采集器  │  │  AI分析引擎  │  │  数据存储器  │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
├─────────────────────────────────────────────────────────────────┤
│                          数据源层                                │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │  Reddit API │  │ Azure Text  │  │  Notion DB  │              │
│  │             │  │ Analytics   │  │             │              │
│  └─────────────┘  └─────────────┘  └─────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 微服务模块设计

#### 2.2.1 数据采集服务 (Collector Service)
```python
# 职责：Reddit 数据采集和初步过滤
class RedditCollector:
    - fetch_new_posts()      # 获取新帖子
    - filter_relevant()      # 相关性过滤
    - extract_comments()     # 提取评论
    - rate_limit_manager()   # 速率限制管理
```

#### 2.2.2 AI分析服务 (Analyzer Service)
```python
# 职责：情感分析、主题分类、影响力评估
class SentimentAnalyzer:
    - analyze_sentiment()    # 情感分析
    - classify_topics()      # 主题分类
    - calculate_influence()  # 影响力评分
    - extract_aspects()      # 方面级情感分析
```

#### 2.2.3 数据存储服务 (Storage Service)
```python
# 职责：数据持久化和查询
class NotionStorage:
    - create_mention()       # 创建提及记录
    - update_mention()       # 更新记录
    - query_mentions()       # 查询数据
    - batch_insert()         # 批量插入
```

#### 2.2.4 预警管理服务 (Alert Service)
```python
# 职责：预警规则检查和通知推送
class AlertManager:
    - check_alert_rules()    # 检查预警规则
    - send_notifications()   # 发送通知
    - manage_alert_levels()  # 管理预警等级
```

#### 2.2.5 调度管理服务 (Scheduler Service)
```python
# 职责：任务调度和流程协调
class TaskScheduler:
    - schedule_collection()  # 调度数据采集
    - coordinate_pipeline()  # 协调数据流水线
    - manage_job_queue()     # 管理任务队列
```

## 3. 数据架构

### 3.1 数据流设计
```
Reddit API → 数据采集 → 相关性过滤 → AI分析 → 数据存储 → 预警检查 → 推送通知
     ↓           ↓          ↓         ↓         ↓          ↓         ↓
   原始数据    清洗数据    过滤数据   分析数据   结构化数据   预警事件   用户通知
```

### 3.2 数据模型设计

#### 3.2.1 核心实体模型
```python
@dataclass
class Mention:
    id: str                    # 唯一标识
    post_id: str              # Reddit 帖子ID
    title: str                # 标题
    content: str              # 内容
    subreddit: str            # 来源社区
    author: str               # 作者
    created_time: datetime    # 创建时间
    score: int                # Reddit评分
    num_comments: int         # 评论数
    
    # AI分析结果
    sentiment_score: float    # 情感分数 (-1 到 1)
    sentiment_label: str      # 正面/中性/负面
    topics: List[str]         # 主题分类
    aspects: Dict[str, float] # 方面级情感
    influence_score: float    # 影响力评分
    
    # 业务字段
    keywords_matched: List[str]  # 匹配关键词
    response_status: str         # 处理状态
    notes: str                   # 人工备注

@dataclass
class Comment:
    id: str
    mention_id: str           # 关联主记录
    content: str
    author: str
    score: int
    sentiment_score: float
    created_time: datetime
```

#### 3.2.2 Notion Database Schema
```python
NOTION_SCHEMA = {
    "Mentions": {
        "ID": {"type": "auto_number"},
        "Post_ID": {"type": "text"},
        "Title": {"type": "title"},
        "Content": {"type": "rich_text"},
        "Subreddit": {"type": "select"},
        "Author": {"type": "text"},
        "Created_Time": {"type": "date"},
        "Sentiment_Score": {"type": "number"},
        "Sentiment_Label": {"type": "select"},
        "Topic_Category": {"type": "multi_select"},
        "Influence_Score": {"type": "number"},
        "Keywords_Matched": {"type": "multi_select"},
        "Response_Status": {"type": "select"},
        "Notes": {"type": "rich_text"},
        "Source_URL": {"type": "url"}
    }
}
```

### 3.3 缓存策略
```python
# 本地SQLite缓存设计
class LocalCache:
    - cache_processed_posts()    # 缓存已处理帖子ID
    - cache_analysis_results()   # 缓存分析结果
    - cache_user_profiles()      # 缓存用户信息
    - manage_cache_expiry()      # 管理缓存过期
```

## 4. 技术实现细节

### 4.1 Reddit API 集成
```python
# Reddit 配置
REDDIT_CONFIG = {
    'client_id': 'your_client_id',
    'client_secret': 'your_client_secret', 
    'user_agent': 'omada-sentiment-monitor v1.0',
    'rate_limit_calls': 100,
    'rate_limit_period': 60
}

# 监控配置
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
    }
}

# 关键词配置
KEYWORDS = {
    'primary': ['omada', 'tp-link omada', 'eap615', 'eap610', 'oc200'],
    'secondary': ['tp-link access point', 'business wifi'],
    'competitor': ['ubiquiti vs tp-link', 'unifi vs omada']
}
```

### 4.2 AI 分析管道
```python
class AnalysisPipeline:
    def __init__(self):
        self.sentiment_analyzer = AzureTextAnalytics()
        self.topic_classifier = OpenAITopicClassifier()
        self.aspect_analyzer = AspectBasedSentimentAnalyzer()
    
    async def analyze_mention(self, mention: Mention) -> Mention:
        # 并行执行多个分析任务
        tasks = [
            self.sentiment_analyzer.analyze(mention.content),
            self.topic_classifier.classify(mention.content),
            self.aspect_analyzer.analyze(mention.content)
        ]
        
        sentiment, topics, aspects = await asyncio.gather(*tasks)
        
        mention.sentiment_score = sentiment.score
        mention.sentiment_label = sentiment.label
        mention.topics = topics
        mention.aspects = aspects
        mention.influence_score = self.calculate_influence(mention)
        
        return mention
```

### 4.3 预警系统设计
```python
# 预警规则配置
ALERT_RULES = {
    'critical': {
        'conditions': [
            'sentiment_score < -0.7 and influence_score > 80',
            'negative_mentions_1h > 5'
        ],
        'notifications': ['email', 'slack', 'wechat'],
        'cooldown': 1800  # 30分钟冷却期
    },
    'high': {
        'conditions': [
            'sentiment_score < -0.5 and score > 50',
            'negative_trend_increase > 200%'
        ],
        'notifications': ['email', 'slack'],
        'cooldown': 3600  # 1小时冷却期
    }
}

class AlertManager:
    def check_alerts(self, mentions: List[Mention]):
        for rule_name, rule in ALERT_RULES.items():
            if self.evaluate_conditions(rule['conditions'], mentions):
                self.trigger_alert(rule_name, rule, mentions)
```

### 4.4 性能优化策略

#### 4.4.1 异步处理
```python
# 使用异步处理提高性能
async def process_mentions_batch(mentions: List[Mention]):
    # 并发处理多个提及
    tasks = [analyze_mention(mention) for mention in mentions]
    analyzed_mentions = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 批量存储到Notion
    await notion_client.batch_create(analyzed_mentions)
```

#### 4.4.2 缓存机制
```python
# Redis缓存热点数据
@lru_cache(maxsize=1000)
def get_user_karma(username: str) -> int:
    return reddit_client.get_user_karma(username)

# 本地缓存API响应
class APICache:
    def __init__(self, ttl: int = 3600):
        self.cache = {}
        self.ttl = ttl
    
    def get_or_fetch(self, key: str, fetch_func):
        if key in self.cache and not self.is_expired(key):
            return self.cache[key]['data']
        
        data = fetch_func()
        self.cache[key] = {
            'data': data,
            'timestamp': time.time()
        }
        return data
```

#### 4.4.3 数据库优化
```python
# SQLite 索引优化
CREATE_INDEXES = [
    "CREATE INDEX idx_post_id ON mentions(post_id)",
    "CREATE INDEX idx_created_time ON mentions(created_time)",
    "CREATE INDEX idx_sentiment_score ON mentions(sentiment_score)",
    "CREATE INDEX idx_subreddit ON mentions(subreddit)"
]
```

## 5. 部署架构

### 5.1 Docker 容器化
```dockerfile
# Dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/ ./src/
COPY config/ ./config/

CMD ["python", "src/main.py"]
```

### 5.2 Docker Compose 编排
```yaml
# docker-compose.yml
version: '3.8'
services:
  omada-sentiment-monitor:
    build: .
    environment:
      - REDDIT_CLIENT_ID=${REDDIT_CLIENT_ID}
      - REDDIT_CLIENT_SECRET=${REDDIT_CLIENT_SECRET}
      - AZURE_TEXT_ANALYTICS_KEY=${AZURE_TEXT_ANALYTICS_KEY}
      - NOTION_TOKEN=${NOTION_TOKEN}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
    
  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    restart: unless-stopped

volumes:
  redis_data:
```

### 5.3 监控和日志
```python
# 日志配置
LOGGING_CONFIG = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'standard': {
            'format': '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
        },
        'json': {
            'format': '%(asctime)s %(levelname)s %(name)s %(message)s',
            'class': 'pythonjsonlogger.jsonlogger.JsonFormatter'
        }
    },
    'handlers': {
        'default': {
            'level': 'INFO',
            'formatter': 'standard',
            'class': 'logging.StreamHandler'
        },
        'file': {
            'level': 'INFO',
            'formatter': 'json',
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': 'logs/omada_monitor.log',
            'maxBytes': 10485760,  # 10MB
            'backupCount': 5
        }
    },
    'loggers': {
        '': {
            'handlers': ['default', 'file'],
            'level': 'INFO',
            'propagate': False
        }
    }
}
```

## 6. 安全性设计

### 6.1 API 密钥管理
- 使用环境变量存储敏感信息
- 实现密钥轮换机制
- API 调用加密传输

### 6.2 数据安全
- 仅收集公开数据
- 数据匿名化处理
- 遵循平台 ToS

### 6.3 系统安全
- 容器镜像安全扫描
- 网络访问控制
- 日志脱敏处理

## 7. 扩展性考虑

### 7.1 数据源扩展
```python
# 数据源接口设计
class DataSourceInterface:
    def fetch_data(self) -> List[Mention]:
        raise NotImplementedError
    
    def get_rate_limits(self) -> Dict:
        raise NotImplementedError

# 新数据源实现
class TwitterCollector(DataSourceInterface):
    def fetch_data(self) -> List[Mention]:
        # Twitter API 实现
        pass
```

### 7.2 分析功能扩展
```python
# 分析器插件系统
class AnalyzerPlugin:
    def analyze(self, content: str) -> Dict:
        raise NotImplementedError

# 自定义分析器
class CompetitorAnalyzer(AnalyzerPlugin):
    def analyze(self, content: str) -> Dict:
        # 竞品对比分析逻辑
        pass
```

### 7.3 通知渠道扩展
```python
# 通知接口
class NotificationChannel:
    def send(self, message: str, recipients: List[str]):
        raise NotImplementedError

# 新通知渠道
class WeChatNotifier(NotificationChannel):
    def send(self, message: str, recipients: List[str]):
        # 微信通知实现
        pass
```

## 8. 监控和运维

### 8.1 健康检查
```python
class HealthChecker:
    def check_reddit_api(self) -> bool:
        # 检查Reddit API连通性
        pass
    
    def check_notion_api(self) -> bool:
        # 检查Notion API连通性  
        pass
    
    def check_disk_space(self) -> bool:
        # 检查磁盘空间
        pass
```

### 8.2 性能监控
- API 调用延迟监控
- 内存使用监控
- 任务执行时间监控
- 错误率监控

### 8.3 告警机制
- 系统异常告警
- 性能阈值告警
- API 配额告警
- 数据质量告警

---

**文档版本**：v1.0  
**创建日期**：2025年6月25日  
**负责人**：技术团队  
**审核状态**：待审核 