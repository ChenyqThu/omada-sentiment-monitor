# Omada 舆情跟踪系统 PRD v1.0

## 产品概述

### 产品愿景
建立自动化的 Omada 品牌舆情监控系统，实时跟踪网络社区中关于 Omada 产品的讨论，通过 AI 分析提供情感趋势洞察，为产品改进和市场策略提供数据支持。

### 核心价值
- **提前发现问题**：负面情感激增预警，快速响应用户问题
- **了解真实需求**：从社区讨论中发现功能改进点
- **竞品情报**：了解用户对 Omada vs 竞品的真实看法
- **产品影响力评估**：量化 Omada 在目标社区的声量和影响力

## 需求分析

### 1. 业务需求
**主要业务目标**：
- 监控 Omada 产品在主要网络社区的提及情况
- 识别负面情感趋势，支持快速响应
- 收集用户功能需求和产品反馈
- 分析竞品对比讨论，为产品策略提供参考

**关键成功指标**：
- 负面提及响应时间 < 2 小时
- 情感分析准确率 > 85%
- 每月发现可执行洞察 > 10 个
- 系统稳定性 > 99%

### 2. 用户需求
**主要用户群体**：
- **产品经理**（源泉）：需要市场洞察和产品反馈
- **技术支持团队**：需要及时发现和处理问题
- **营销团队**：需要了解品牌声誉和竞品对比
- **研发团队**：需要用户功能需求反馈

**用户使用场景**：
- 每日查看情感趋势仪表板
- 接收负面情感激增预警邮件
- 深入分析特定话题的用户讨论
- 生成月度/季度舆情分析报告

### 3. 技术需求
**数据源要求**：
- **Reddit 社区**：r/homenetworking, r/networking, r/sysadmin, r/TPLINK
- **覆盖范围**：实时监控 + 7 天历史数据
- **数据量估算**：每日 50-100 条相关提及

**性能要求**：
- **实时性**：15 分钟内检测到新提及
- **准确性**：情感分析准确率 > 85%
- **可靠性**：99% 系统可用性
- **扩展性**：支持新增数据源和关键词

## 功能规格

### 1. 数据采集模块

#### 1.1 Reddit 监控
**技术实现**：
- 使用 PRAW (Python Reddit API Wrapper)
- OAuth 2.0 认证，免费套餐（100 QPM）
- 智能率限管理和错误重试

**监控范围**：
```python
TARGET_SUBREDDITS = {
    'homenetworking': {'priority': 'high', 'check_interval': 5},  # 每5分钟
    'networking': {'priority': 'high', 'check_interval': 10},     # 每10分钟  
    'sysadmin': {'priority': 'medium', 'check_interval': 15},     # 每15分钟
    'TPLINK': {'priority': 'high', 'check_interval': 5}          # 每5分钟
}

KEYWORDS = {
    'primary': ['omada', 'tp-link omada', 'eap615', 'eap610', 'oc200'],
    'secondary': ['tp-link access point', 'business wifi', 'prosumer networking'],
    'competitor': ['ubiquiti vs tp-link', 'unifi vs omada', 'alternative to unifi']
}
```

**数据字段**：
- 帖子基础信息：ID、标题、内容、作者、时间、评分
- 互动数据：评论数、点赞数、分享数
- 评论内容：前 20 个相关评论
- 元数据：subreddit、permalink、flair

#### 1.2 数据质量保证
- **去重机制**：基于帖子 ID 避免重复处理
- **相关性过滤**：AI 判断内容与 Omada 产品的相关性（阈值 > 0.7）
- **噪音过滤**：排除明显的垃圾内容和机器人发帖

### 2. AI 分析模块

#### 2.1 情感分析引擎
**技术选型**：
- **主引擎**：Azure Text Analytics（准确性高，支持中英文）
- **备用引擎**：AWS Comprehend（成本优化）
- **本地模型**：VADER（离线备份，免费）

**分析维度**：
```python
SENTIMENT_CATEGORIES = {
    'overall': ['positive', 'neutral', 'negative'],  # 整体情感
    'aspects': {
        'product_quality': '产品质量',
        'software_experience': '软件体验', 
        'price_value': '性价比',
        'support_service': '技术支持',
        'reliability': '可靠性'
    },
    'emotions': ['satisfaction', 'frustration', 'excitement', 'disappointment']
}
```

#### 2.2 主题分类
使用 LLM (Claude-3.5-Sonnet) 进行智能分类：
- **产品功能**：WiFi 性能、管理界面、硬件设计
- **技术问题**：连接问题、配置困难、bug 报告
- **购买决策**：产品对比、推荐请求、替代方案
- **竞品对比**：Omada vs Ubiquiti、价格对比、功能对比

#### 2.3 影响力评估
**评分算法**：
```python
def calculate_influence_score(post_data):
    base_score = post_data['score'] * 0.4  # Reddit 评分权重
    engagement = post_data['num_comments'] * 0.3  # 评论数权重
    author_karma = post_data['author_karma'] * 0.0001  # 作者声誉
    subreddit_multiplier = SUBREDDIT_WEIGHTS[post_data['subreddit']]
    
    return (base_score + engagement + author_karma) * subreddit_multiplier
```

### 3. 数据存储模块

#### 3.1 Notion Database 设计
**主表：Mentions**
| 字段名 | 类型 | 说明 |
|--------|------|------|
| ID | 自动编号 | 主键 |
| Post_ID | 文本 | Reddit 帖子 ID |
| Title | 标题 | 帖子标题 |
| Content | 富文本 | 帖子内容摘要 |
| Subreddit | 选择 | 来源社区 |
| Author | 文本 | 作者用户名 |
| Created_Time | 日期 | 发布时间 |
| Sentiment_Score | 数字 | 情感分数 (-1 到 1) |
| Sentiment_Label | 选择 | 正面/中性/负面 |
| Topic_Category | 多选 | 主题分类 |
| Influence_Score | 数字 | 影响力评分 |
| Keywords_Matched | 多选 | 匹配的关键词 |
| Response_Status | 选择 | 未处理/已关注/已响应 |
| Notes | 富文本 | 人工备注 |
| Source_URL | URL | 原始链接 |

**关联表：Comments**
| 字段名 | 类型 | 说明 |
|--------|------|------|
| ID | 自动编号 | 主键 |
| Mention_ID | 关联 | 关联主表 |
| Comment_Text | 富文本 | 评论内容 |
| Comment_Score | 数字 | 评论评分 |
| Sentiment_Score | 数字 | 评论情感分数 |

#### 3.2 Notion API 集成
```python
# Notion 数据写入示例
import requests

def create_mention_record(mention_data):
    notion_url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    data = {
        "parent": {"database_id": DATABASE_ID},
        "properties": {
            "Title": {"title": [{"text": {"content": mention_data['title']}}]},
            "Post_ID": {"rich_text": [{"text": {"content": mention_data['post_id']}}]},
            "Sentiment_Score": {"number": mention_data['sentiment_score']},
            "Sentiment_Label": {"select": {"name": mention_data['sentiment_label']}},
            # ... 其他字段
        }
    }
    
    response = requests.post(notion_url, headers=headers, json=data)
    return response.json()
```

### 4. 预警与推送模块

#### 4.1 实时预警
**触发条件**：
- 负面情感帖子评分 > 50 且评论数 > 20
- 1 小时内负面提及数量 > 5
- 高影响力用户（karma > 10k）发布负面内容
- 竞品对比中 Omada 明显处于劣势

**预警等级**：
```python
ALERT_LEVELS = {
    'critical': {
        'conditions': '高影响力负面提及',
        'notification': ['邮件', '微信', 'Slack'],
        'response_time': '30分钟'
    },
    'high': {
        'conditions': '负面情感激增',
        'notification': ['邮件', 'Slack'], 
        'response_time': '2小时'
    },
    'medium': {
        'conditions': '单个高分负面帖子',
        'notification': ['邮件'],
        'response_time': '4小时'
    }
}
```

#### 4.2 日报邮件
**发送时间**：每日上午 9:00（北京时间）
**邮件内容**：
- **执行摘要**：昨日关键数据和趋势
- **情感分析**：正负面比例、情感变化趋势
- **热点话题**：高讨论度的主题和问题
- **竞品对比**：Omada vs 竞品的提及对比
- **行动建议**：需要关注或响应的内容

#### 4.3 周报和月报
**周报**（每周一发送）：
- 一周情感趋势分析
- 主要问题汇总和分析
- 竞品对比深度分析
- 功能需求收集

**月报**（每月 1 号发送）：
- 月度舆情总结
- 情感改善/恶化趋势
- 产品问题根因分析  
- 营销和产品建议

### 5. Dashboard 展示

#### 5.1 实时监控面板
**核心指标**：
- 今日提及数量和情感分布
- 实时情感趋势图（24小时）
- 热门讨论话题词云
- 预警状态和待处理事项

#### 5.2 分析报表
**情感趋势分析**：
- 7天/30天/90天情感变化曲线
- 不同 subreddit 的情感对比
- 产品功能维度的情感分析

**竞品对比分析**：
- Omada vs Ubiquiti 提及量对比
- 用户选择倾向分析
- 价格敏感度分析

## 技术架构

### 1. 系统架构图
```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   数据采集层     │    │    AI 分析层      │    │   存储与展示层   │
├─────────────────┤    ├──────────────────┤    ├─────────────────┤
│ • Reddit API    │────│ • 情感分析引擎    │────│ • Notion DB     │
│ • PRAW 包装器   │    │ • 主题分类模型    │    │ • Dashboard     │ 
│ • 定时调度器    │    │ • 影响力评估     │    │ • 邮件推送      │
│ • 错误重试      │    │ • 相关性判断     │    │ • 预警系统      │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### 2. 技术栈选择
**后端服务**：
- **语言**：Python 3.11+
- **API 包装器**：PRAW 7.8.1+（Reddit API）
- **AI 服务**：Azure Text Analytics + OpenAI GPT-4
- **调度器**：APScheduler（轻量级定时任务）
- **数据库**：Notion API + 本地 SQLite（缓存）

**部署环境**：
- **云平台**：AWS / 阿里云
- **容器化**：Docker + Docker Compose
- **服务模式**：微服务架构
- **监控**：CloudWatch + 自定义健康检查

### 3. 数据流设计
```python
# 主数据流程
def main_pipeline():
    # 1. 数据采集
    raw_posts = reddit_collector.fetch_new_posts()
    
    # 2. 数据清洗和过滤
    relevant_posts = filter_relevant_content(raw_posts)
    
    # 3. AI 分析
    analyzed_posts = []
    for post in relevant_posts:
        sentiment = sentiment_analyzer.analyze(post['content'])
        topics = topic_classifier.classify(post['content'])
        influence = calculate_influence_score(post)
        
        analyzed_posts.append({
            **post,
            'sentiment': sentiment,
            'topics': topics, 
            'influence_score': influence
        })
    
    # 4. 存储到 Notion
    for post in analyzed_posts:
        notion_client.create_record(post)
    
    # 5. 预警检查
    alert_manager.check_alerts(analyzed_posts)
    
    # 6. 更新 dashboard
    dashboard.refresh_data()
```

## 实施计划

### Phase 1: MVP 开发（4-6 周）
**目标**：基础监控和情感分析功能
**功能范围**：
- Reddit 数据采集（1-2 个 subreddit）
- 基础情感分析
- Notion 数据存储
- 简单日报邮件

**技术实现**：
- 搭建 Python 开发环境
- 集成 PRAW 和 Reddit API
- 实现基础情感分析
- 配置 Notion API 集成

**成功标准**：
- 稳定监控 r/homenetworking 和 r/networking
- 日处理 20-50 条相关提及
- 情感分析基础可用
- 每日邮件正常发送

### Phase 2: 完整功能（6-8 周）
**目标**：完整的舆情监控系统
**功能扩展**：
- 多 subreddit 监控
- 高级 AI 分析（主题分类、影响力评估）
- 实时预警系统
- Dashboard 展示

**技术优化**：
- 性能优化和错误处理
- 多线程数据处理
- 缓存机制
- 监控和日志系统

### Phase 3: 优化与扩展（4-6 周）
**目标**：系统优化和功能扩展  
**优化项目**：
- AI 模型调优（针对网络设备领域）
- 用户界面优化
- 报表和分析功能
- 系统性能调优

**扩展功能**：
- 竞品监控
- 历史数据分析
- 自定义关键词和预警规则
- API 开放给其他团队

## 成本估算

### 1. 开发成本
- **人力成本**：2-3 人月（1 个后端 + 0.5 个前端 + 0.5 个 AI）
- **外包开发**：15-25 万人民币

### 2. 运营成本（月度）
| 项目 | 成本（元/月） | 说明 |
|------|--------------|------|
| Reddit API | 0 | 免费 OAuth 套餐 |
| Azure Text Analytics | 200-500 | 基于调用量 |
| Notion Pro | 200 | 团队版本 |
| 云服务器 | 300-800 | AWS/阿里云 |
| 域名和 SSL | 50 | 基础设施 |
| **总计** | **750-1,550** | 预计月运营成本 |

### 3. ROI 分析
**投资回报评估**：
- **硬性节省**：减少 50% 负面问题处理时间，节省客服成本
- **软性价值**：产品改进洞察、市场策略优化、品牌声誉管理
- **预期 ROI**：12-18 个月达到盈亏平衡

## 风险评估

### 1. 技术风险
**Reddit API 政策变化**：
- **风险等级**：中等
- **缓解措施**：多数据源备份、RSS 订阅备用方案

**AI 分析准确性**：
- **风险等级**：中等  
- **缓解措施**：多引擎验证、人工标注数据集、持续模型优化

### 2. 运营风险
**数据合规性**：
- **风险等级**：低
- **缓解措施**：仅收集公开数据、遵循平台 ToS、数据匿名化处理

**系统稳定性**：
- **风险等级**：中等
- **缓解措施**：健壮的错误处理、多重备份、监控告警

### 3. 业务风险
**功能期望过高**：
- **风险等级**：中等
- **缓解措施**：分阶段交付、设定合理期望、持续沟通

## 项目时间线

```
2025 Q3:
├── Week 1-2: 需求确认和技术选型
├── Week 3-6: MVP 开发
├── Week 7-8: 内测和优化
└── Week 9: MVP 上线

2025 Q4:  
├── Week 1-4: 完整功能开发
├── Week 5-6: 系统测试和优化
├── Week 7-8: 用户培训和部署
└── Week 9-12: 运营优化和功能扩展
```

## 成功标准

### 1. 系统性能指标
- **可用性**：> 99%
- **响应时间**：数据更新延迟 < 15 分钟
- **准确性**：情感分析准确率 > 85%

### 2. 业务价值指标
- **覆盖度**：捕获 > 95% 的相关提及
- **响应效率**：负面问题响应时间 < 2 小时
- **洞察价值**：每月产生 > 10 个可执行洞察

### 3. 用户满意度指标
- **使用频率**：团队成员每周使用 > 3 次
- **满意度评分**：> 4.0/5.0
- **功能采用率**：> 80% 功能被定期使用

---

**文档版本**：v1.0  
**最后更新**：2025年6月25日  
**负责人**：陈源泉  
**审核状态**：待审核