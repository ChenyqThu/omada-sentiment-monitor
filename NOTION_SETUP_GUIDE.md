# Notion 同步设置指南

## 概述

本指南将帮助您配置 Notion Database 用于 Omada 舆情监控系统的数据同步。系统会将 Reddit 帖子、评论和 AI 分析结果自动同步到您的 Notion Database 中。

## 第一步：创建 Notion Integration

1. 访问 [Notion Integrations](https://www.notion.so/my-integrations)
2. 点击 "New integration"
3. 填写基本信息：
   - **Name**: Omada Sentiment Monitor
   - **Logo**: 可选
   - **Associated workspace**: 选择您的工作空间
4. 点击 "Submit"
5. 复制生成的 **Internal Integration Token**（以 `secret_` 开头）

## 第二步：创建 Notion Database

### 方法一：使用模板创建（推荐）

1. 复制以下 Notion 页面模板：

```
标题: Omada 舆情监控数据库

这是一个用于存储 Reddit 舆情数据的数据库。

Database 属性配置：
- 标题 (Title)
- 内容 (Text) 
- 类型 (Select: Post, Comment)
- 来源 (Select: Reddit)
- Subreddit (Text)
- 作者 (Text)
- 分数 (Number)
- 评论数 (Number)
- 发布时间 (Date)
- 采集时间 (Date)
- Reddit链接 (URL)
- 影响力评分 (Number)
- 用户Karma (Number)
- 相关性得分 (Number)
- 匹配关键词 (Multi-select)
- 情感倾向 (Select: 正面, 负面, 中性)
- 情感分数 (Number)
- 置信度 (Number)
- 关键词 (Multi-select)
- 主题分类 (Multi-select)
- AI摘要 (Text)
- 分析器类型 (Text)
- 优先级 (Select: 高, 中, 低)
- 是否已处理 (Checkbox)
- 处理备注 (Text)
- 产品型号 (Multi-select)
- 问题类型 (Multi-select)
- 竞品提及 (Multi-select)
```

### 方法二：手动创建

1. 在 Notion 中创建新页面
2. 添加 Database（Table 视图）
3. 按照以下规范添加属性：

#### 基础信息字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 标题 | Title | 帖子标题（主键） |
| 内容 | Text | 帖子内容摘要 |
| 类型 | Select | Post, Comment |
| 来源 | Select | Reddit |
| Subreddit | Text | 来源子版块 |
| 作者 | Text | Reddit 用户名 |
| 分数 | Number | Reddit 评分 |
| 评论数 | Number | 评论数量 |
| 发布时间 | Date | 原始发布时间 |
| 采集时间 | Date | 系统采集时间 |
| Reddit链接 | URL | 原始链接 |

#### 影响力字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| 影响力评分 | Number | 0-10分 |
| 用户Karma | Number | 用户声誉值 |
| 相关性得分 | Number | 0-1分 |
| 匹配关键词 | Multi-select | 触发关键词 |

#### AI 分析字段

| 字段名 | 类型 | 选项/说明 |
|--------|------|----------|
| 情感倾向 | Select | 正面, 负面, 中性 |
| 情感分数 | Number | -1.0 到 1.0 |
| 置信度 | Number | 0.0 到 1.0 |
| 关键词 | Multi-select | AI 提取的关键词 |
| 主题分类 | Multi-select | 产品推荐, 技术问题, 安装配置, 故障排除, 竞品对比 等 |
| AI摘要 | Text | AI 生成的摘要 |
| 分析器类型 | Text | local, openai, azure |

#### 监控字段

| 字段名 | 类型 | 选项/说明 |
|--------|------|----------|
| 优先级 | Select | 高, 中, 低 |
| 是否已处理 | Checkbox | 人工处理标记 |
| 处理备注 | Text | 处理说明 |
| 产品型号 | Multi-select | EAP610, EAP615, Archer AX73 等 |
| 问题类型 | Multi-select | 连接问题, 配置问题, 性能问题 等 |
| 竞品提及 | Multi-select | Ubiquiti, Aruba, Cisco 等 |

## 第三步：获取 Database ID

1. 打开您创建的 Database 页面
2. 点击右上角的 "Share" 按钮
3. 点击 "Copy link"
4. 从链接中提取 Database ID：
   ```
   https://www.notion.so/workspace/数据库名称-DATABASE_ID?v=...
   ```
   Database ID 是 32 位字符串（中间有连字符）

## 第四步：授权 Integration

1. 在 Database 页面点击右上角的 "..." 菜单
2. 选择 "Add connections"
3. 搜索并选择您创建的 Integration "Omada Sentiment Monitor"
4. 点击 "Confirm"

## 第五步：配置环境变量

将以下配置添加到您的 `.env` 文件：

```bash
# Notion API 配置
NOTION_TOKEN=secret_your_integration_token_here
NOTION_DATABASE_ID=your_database_id_here
NOTION_API_VERSION=2022-06-28
NOTION_MAX_RETRIES=3
NOTION_TIMEOUT=30
NOTION_REQUIRED=false
```

## 第六步：测试连接

运行测试命令验证配置：

```bash
# 测试 Notion 连接和同步
python src/main.py --test-notion

# 或者使用独立测试脚本
python test_notion_sync.py
```

成功输出示例：
```
🧪 Notion 同步功能测试
==================================================
✅ Notion 配置已启用
📊 Database ID: 12345678...

🔗 测试 Notion 连接...
状态: healthy
✅ 数据库标题: Omada 舆情监控数据库
📊 字段数量: 25

📝 测试数据同步...
✅ 同步成功！页面 ID: page_id_here
✅ 测试完成，请检查您的 Notion Database
```

## 第七步：运行完整流程

现在您可以运行完整的监控流程：

```bash
# 单次执行（包含采集、分析、同步）
python src/main.py --mode single

# 持续监控
python src/main.py --mode continuous

# 健康检查
python src/main.py --mode health
```

## 推荐的 Database 视图

### 1. 主监控视图
- **过滤器**: 优先级 = 高 或 中
- **排序**: 采集时间（降序）
- **显示字段**: 标题, 情感倾向, 优先级, Subreddit, 分数, 采集时间

### 2. 情感分析视图
- **分组**: 情感倾向
- **排序**: 情感分数（降序）
- **显示字段**: 标题, 情感分数, 置信度, AI摘要

### 3. 产品问题视图
- **过滤器**: 问题类型 ≠ 空
- **分组**: 产品型号
- **显示字段**: 标题, 问题类型, 优先级, 处理状态

### 4. 竞品分析视图
- **过滤器**: 竞品提及 ≠ 空
- **分组**: 竞品提及
- **显示字段**: 标题, 情感倾向, 主题分类, 影响力评分

## Notion AI Column 配置（可选）

如果您想使用 Notion AI 进行分析，请参考 `notion_ai_prompts.md` 文件中的详细 Prompt 配置。

主要字段的 AI Column 配置：
- **情感倾向**: 使用情感分析 Prompt
- **AI摘要**: 使用摘要生成 Prompt  
- **关键词**: 使用关键词提取 Prompt
- **主题分类**: 使用主题分类 Prompt

## 故障排除

### 常见错误

1. **"Notion Token 未配置"**
   - 检查 `.env` 文件中的 `NOTION_TOKEN`
   - 确保 Token 以 `secret_` 开头

2. **"Notion Database ID 未配置"**
   - 检查 `.env` 文件中的 `NOTION_DATABASE_ID`
   - 确保 Database ID 格式正确（32位，包含连字符）

3. **"API错误: object_not_found"**
   - 检查 Database ID 是否正确
   - 确保 Integration 已被授权访问该 Database

4. **"API错误: unauthorized"**
   - 检查 Integration Token 是否正确
   - 确保 Integration 有权限访问工作空间

5. **字段类型不匹配**
   - 检查 Database 字段类型是否与配置匹配
   - 参考上面的字段类型表格

### 调试技巧

1. **启用调试日志**:
   ```bash
   export LOG_LEVEL=DEBUG
   python src/main.py --test-notion
   ```

2. **检查 Database 结构**:
   - 运行测试会显示检测到的字段数量
   - 确保所有必需字段都已创建

3. **验证数据格式**:
   - 查看测试同步的数据是否正确显示
   - 检查日期、数字、选择字段的格式

## 数据管理建议

1. **定期清理**: 设置自动化规则删除超过 30 天的数据
2. **备份重要数据**: 导出关键分析结果
3. **监控使用量**: 注意 Notion API 调用限制
4. **优化性能**: 避免在高峰时段进行大量同步

## 扩展功能

您可以基于同步的数据创建：
- **仪表板**: 使用 Notion 图表功能
- **自动化**: 设置 Notion 自动化规则
- **报告**: 定期导出数据生成报告
- **预警**: 基于优先级设置通知 