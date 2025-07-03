# Omada 舆情监控系统 🚀

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Compose-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

基于 Python 和 PRAW 的 Reddit 舆情监控系统，专门用于跟踪 Omada 产品在网络社区中的讨论和情感分析。

## 📋 项目简介

### 🎯 核心功能
- 🔍 **Reddit 社区监控** - 自动监控 r/homenetworking, r/networking, r/sysadmin, r/TPLINK 等社区
- 🤖 **多种 AI 分析** - 支持 OpenAI、Azure、本地规则等多种分析方式
- 📊 **数据存储** - 集成 Notion Database 进行结构化数据存储
- ⚡ **实时预警** - 负面情感激增时自动邮件预警
- 📈 **影响力评估** - 基于用户 karma、帖子评分等维度评估影响力

### 🏗️ 技术架构
- **后端**: Python 3.11+, PRAW, APScheduler
- **AI 服务**: 支持 OpenAI GPT、Azure Text Analytics、本地规则分析
- **数据存储**: Notion API + SQLite 缓存
- **部署**: Docker + Docker Compose
- **监控**: 自定义日志系统 + 健康检查

### 🎯 项目价值
- **提前发现问题**: 负面情感激增预警，快速响应用户问题
- **了解真实需求**: 从社区讨论中发现用户痛点和需求
- **竞品分析**: 监控竞争对手产品的用户反馈
- **产品改进**: 基于真实用户反馈指导产品优化方向

## 🤖 AI 分析器选择指南

系统支持多种 AI 分析方式，您可以根据需求和预算选择：

### 📊 分析器对比

| 分析器 | 优势 | 劣势 | 适用场景 | 成本 |
|--------|------|------|----------|------|
| **本地规则** | 免费、快速、稳定 | 准确性有限 | 快速测试、离线使用 | 免费 |
| **OpenAI GPT** | 准确性高、支持第三方API | 需要API费用 | 生产环境、高质量分析 | 按使用量 |
| **Azure Text Analytics** | 企业级、稳定性好 | 配置复杂、费用较高 | 企业环境、合规要求 | 按使用量 |
| **Notion AI** | 集成度高 | 功能有限（计划中） | Notion 深度用户 | 计划中 |

### 🔧 配置说明

#### 1. **本地规则分析器** (推荐入门)
```bash
# .env 配置
AI_ANALYZER_TYPE=local
```

**特点**:
- ✅ 无需外部 API，完全免费
- ✅ 响应速度快，无网络依赖
- ✅ 支持中英文情感分析
- ⚠️ 准确性相对较低，适合初步筛选

#### 2. **OpenAI 分析器** (推荐生产)
```bash
# .env 配置
AI_ANALYZER_TYPE=openai
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_BASE_URL=https://api.openai.com/v1  # 支持第三方 API
OPENAI_MODEL=gpt-3.5-turbo
```

**第三方 API 支持**:
```bash
# 使用国内第三方 API 示例
OPENAI_BASE_URL=https://api.deepseek.com/v1
OPENAI_MODEL=deepseek-chat

# 或其他兼容 OpenAI 格式的 API
OPENAI_BASE_URL=https://your-custom-api.com/v1
```

**特点**:
- ✅ 分析准确性高，理解上下文
- ✅ 支持复杂情感和主题分析
- ✅ 可使用第三方兼容 API，降低成本
- ⚠️ 需要 API 费用，按使用量计费

#### 3. **Azure Text Analytics**
```bash
# .env 配置
AI_ANALYZER_TYPE=azure
AZURE_TEXT_ANALYTICS_KEY=your_azure_key_here
AZURE_TEXT_ANALYTICS_ENDPOINT=https://your-resource.cognitiveservices.azure.com/
```

**特点**:
- ✅ 企业级服务，稳定性好
- ✅ 微软官方支持，合规性强
- ✅ 支持多语言分析
- ⚠️ 配置相对复杂，费用较高

## 🚀 快速开始

### 📋 环境要求
- Python 3.11+
- Git
- Docker (可选)

### 🔑 第三方服务账号准备

| 服务 | 用途 | 申请地址 | 费用 | 必需性 |
|------|------|----------|------|--------|
| Reddit API | 数据采集 | [Reddit Apps](https://www.reddit.com/prefs/apps) | 免费 | ✅ 必需 |
| OpenAI API | AI分析 | [OpenAI Platform](https://platform.openai.com) | 按量付费 | 🔄 可选 |
| Azure Cognitive | AI分析 | [Azure Portal](https://portal.azure.com) | 按量付费 | 🔄 可选 |
| Notion API | 数据存储 | [Notion Integrations](https://www.notion.so/my-integrations) | 免费/付费 | 🔄 可选 |
| SMTP邮箱 | 预警推送 | Gmail/企业邮箱 | 免费 | 🔄 可选 |

### 📦 Docker 部署 (推荐)

```bash
# 1. 克隆项目
git clone <repository_url>
cd omada-sentiment-monitor

# 2. 配置环境变量
cp .env.template .env
# 编辑 .env 文件，填入你的 API 密钥

# 3. 启动服务
docker-compose up -d

# 4. 查看日志
docker-compose logs -f
```

### 💻 本地开发

```bash
# 1. 克隆项目
git clone <repository_url>
cd omada-sentiment-monitor

# 2. 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3. 安装依赖
pip install -r requirements.txt

# 4. 配置环境变量
cp .env.template .env
# 编辑 .env 文件

# 5. 测试配置
python src/main.py --config-check

# 6. 测试 AI 分析器
python src/main.py --test-analyzer

# 7. 运行单次采集
python src/main.py --mode single

# 8. 启动持续监控
python src/main.py --mode continuous
```

## 📁 项目结构

```
omada-sentiment-monitor/
├── 📁 src/                     # 源代码
│   ├── 📁 analyzers/           # AI 分析器模块
│   │   ├── base_analyzer.py    # 分析器基类
│   │   ├── openai_analyzer.py  # OpenAI 分析器
│   │   ├── local_analyzer.py   # 本地规则分析器
│   │   └── analyzer_factory.py # 分析器工厂
│   ├── 📁 collectors/          # 数据采集模块
│   │   └── reddit_collector.py # Reddit 采集器
│   ├── 📁 storage/             # 数据存储模块
│   ├── 📁 utils/               # 工具模块
│   │   ├── logger.py           # 日志系统
│   │   └── cache.py            # 缓存管理
│   └── main.py                 # 主程序入口
├── 📁 config/                  # 配置管理
│   └── settings.py             # 配置定义
├── 📁 logs/                    # 日志文件
├── 📁 data/                    # 数据文件
├── 📄 .env.template            # 环境变量模板
├── 📄 requirements.txt         # Python 依赖
├── 📄 Dockerfile               # Docker 镜像
├── 📄 docker-compose.yml       # Docker 编排
└── 📄 README.md               # 项目说明
```

## ⚙️ 配置说明

### 🔍 监控规则配置

```bash
# 目标 Subreddit (逗号分隔)
TARGET_SUBREDDITS=homenetworking,networking,sysadmin,TPLINK

# 主要关键词 (高权重)
PRIMARY_KEYWORDS=omada,tp-link,tplink,access point,archer,deco,eap

# 次要关键词 (低权重)  
SECONDARY_KEYWORDS=wifi 6,wifi setup,business wifi,mesh network,poe switch

# 相关性阈值 (0.0-1.0，越高越严格)
RELEVANCE_THRESHOLD=0.3

# 每个 subreddit 最大帖子数
MAX_POSTS_PER_SUBREDDIT=25
```

### 📧 预警配置

```bash
# 负面情感阈值 (超过此比例触发预警)
NEGATIVE_SENTIMENT_THRESHOLD=0.7

# 负面帖子数量阈值
NEGATIVE_POSTS_THRESHOLD=5

# 预警检查间隔 (秒)
ALERT_CHECK_INTERVAL=3600
```

## 🎮 使用指南

### 📊 命令行操作

```bash
# 配置检查
python src/main.py --config-check

# AI 分析器测试
python src/main.py --test-analyzer

# 单次数据采集
python src/main.py --mode single

# 持续监控模式
python src/main.py --mode continuous

# 健康检查
python src/main.py --mode health

# 调试模式 (降低阈值，显示详细信息)
python src/main.py --mode single --debug

# 缓存管理
python src/main.py --cache-stats    # 查看缓存统计
python src/main.py --cache-clear    # 清空缓存
```

### 🔧 Docker 操作

```bash
# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f

# 重启服务
docker-compose restart

# 停止服务
docker-compose down

# 进入容器
docker-compose exec monitor bash

# 查看容器状态
docker-compose ps
```

## 📊 监控和维护

### 📈 日志监控

```bash
# 查看实时日志
tail -f logs/omada_monitor.log

# 查看错误日志
grep "ERROR" logs/omada_monitor.log

# 查看采集统计
grep "采集结果摘要" logs/omada_monitor.log
```

### 🔍 性能监控

```bash
# 系统健康检查
python src/main.py --mode health

# 缓存使用情况
python src/main.py --cache-stats

# AI 分析器状态
python src/main.py --test-analyzer
```

## 🚨 故障排除

### ❌ 常见问题

#### 1. **Reddit API 连接失败**
```bash
# 检查配置
python src/main.py --config-check

# 可能原因：
# - API 密钥错误
# - 网络连接问题
# - Reddit API 限制
```

#### 2. **AI 分析器错误**
```bash
# 测试分析器
python src/main.py --test-analyzer

# 常见解决方案：
# - 检查 API 密钥是否正确
# - 确认网络可访问 API 端点
# - 切换到本地分析器：AI_ANALYZER_TYPE=local
```

#### 3. **采集结果为空**
```bash
# 使用调试模式
python src/main.py --mode single --debug

# 可能原因：
# - 关键词设置过于严格
# - 相关性阈值过高
# - 缓存中已有数据被跳过
```

#### 4. **环境变量问题**
```bash
# 检查环境变量格式
# 确保没有多余空格或注释
# 重新启动程序重新加载配置
```

### 🔄 故障恢复

```bash
# 清空缓存重新开始
python src/main.py --cache-clear

# 重置配置
cp .env.template .env
# 重新配置 .env 文件

# 重新安装依赖
pip install -r requirements.txt --upgrade
```

## 🗺️ 开发路线图

### ✅ **Phase 1: MVP (已完成)**
- ✅ Reddit 数据采集
- ✅ 多种 AI 分析器支持
- ✅ 本地缓存系统
- ✅ 基础日志和监控

### 🚧 **Phase 2: 完整功能 (开发中)**
- 🔄 Notion Database 集成
- 🔄 邮件预警系统
- 🔄 Azure Text Analytics 集成
- 🔄 Dashboard 展示界面

### 📋 **Phase 3: 优化扩展 (计划中)**
- 📋 Notion AI 分析器
- 📋 高级分析和报表
- 📋 API 接口开放
- 📋 Web 管理界面

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📝 许可证

本项目采用 MIT 许可证 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 支持

如果您遇到问题或有建议，请：

1. 查看[故障排除](#-故障排除)部分
2. 搜索现有的 [Issues](../../issues)
3. 创建新的 [Issue](../../issues/new)

---

⭐ 如果这个项目对您有帮助，请给它一个星标！ 