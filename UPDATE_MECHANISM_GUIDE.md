# Notion 更新机制说明

## 功能概述

系统现在支持智能更新已存在的帖子，而不是重复创建新页面。当监控到已存在帖子的热度或评论数发生较大变化时，系统会自动更新 Notion 中对应的页面。

## 更新触发条件

系统会在以下情况下更新已存在的帖子：

### 1. 分数变化触发
- **百分比阈值**: 分数变化超过 20% (可配置 `NOTION_SCORE_CHANGE_THRESHOLD`)
- **最小绝对值**: 分数变化至少 5 分 (可配置 `NOTION_SCORE_CHANGE_MIN`)
- **示例**: 帖子从 10 分变为 25 分，变化 150%，触发更新

### 2. 评论数变化触发
- **百分比阈值**: 评论数变化超过 30% (可配置 `NOTION_COMMENTS_CHANGE_THRESHOLD`)
- **最小绝对值**: 评论数变化至少 2 个 (可配置 `NOTION_COMMENTS_CHANGE_MIN`)
- **示例**: 帖子从 5 个评论变为 10 个评论，变化 100%，触发更新

### 3. 热门帖子特殊规则
- **分数阈值**: 帖子分数超过 100 分 (可配置 `NOTION_HOT_POST_SCORE_THRESHOLD`)
- **最小变化**: 分数变化至少 10 分 (可配置 `NOTION_HOT_POST_SCORE_CHANGE_MIN`)
- **示例**: 热门帖子从 120 分变为 135 分，触发更新

### 4. 热议帖子特殊规则
- **评论数阈值**: 评论数超过 50 个 (可配置 `NOTION_POPULAR_POST_COMMENTS_THRESHOLD`)
- **最小变化**: 评论数变化至少 5 个 (可配置 `NOTION_POPULAR_POST_COMMENTS_CHANGE_MIN`)
- **示例**: 热议帖子从 60 个评论变为 70 个评论，触发更新

## 更新的字段

当帖子需要更新时，系统会更新以下内容：

### 页面属性更新
- ✅ **分数**: 最新的 Reddit 分数
- ✅ **评论数**: 最新的评论数量
- ✅ **影响力评分**: 根据新分数重新计算
- ✅ **最后更新时间**: 记录更新时间
- ✅ **相关性得分**: 最新的相关性计算结果
- ✅ **优先级**: 根据新影响力重新计算
- ✅ **AI 分析结果**: 如果启用了 AI 分析，会重新分析内容

### 页面内容更新
- ✅ **评论内容**: 当评论数发生显著变化时，会重新写入所有评论
- ✅ **帖子信息**: 更新分数、评论数等元数据
- ✅ **完整替换**: 删除原有内容，重新写入最新内容（避免重复和混乱）
- ❌ **原始链接**: 已移除，减少冗余信息

## 配置选项

在 `.env` 文件中添加以下配置来自定义更新行为：

```bash
# 启用/禁用更新机制
NOTION_ENABLE_UPDATE=true

# 分数变化触发条件
NOTION_SCORE_CHANGE_THRESHOLD=20.0    # 分数变化百分比阈值
NOTION_SCORE_CHANGE_MIN=5             # 分数变化最小绝对值

# 评论数变化触发条件
NOTION_COMMENTS_CHANGE_THRESHOLD=30.0 # 评论数变化百分比阈值
NOTION_COMMENTS_CHANGE_MIN=2          # 评论数变化最小绝对值

# 热门帖子触发条件
NOTION_HOT_POST_SCORE_THRESHOLD=100   # 热门帖子分数阈值
NOTION_HOT_POST_SCORE_CHANGE_MIN=10   # 热门帖子分数变化最小值

# 热议帖子触发条件
NOTION_POPULAR_POST_COMMENTS_THRESHOLD=50  # 热议帖子评论数阈值
NOTION_POPULAR_POST_COMMENTS_CHANGE_MIN=5  # 热议帖子评论数变化最小值
```

## Notion 数据库结构更新

为了支持更新机制，Notion 数据库需要包含以下字段：

### 必需字段
- **Reddit ID** (Rich Text): 用于唯一标识 Reddit 帖子
- **最后更新时间** (Date): 记录最后一次更新的时间

### 建议字段结构
```
标题 (Title)
内容 (Rich Text)
Reddit ID (Rich Text) ← 新增，必需
类型 (Select)
来源 (Select)
Subreddit (Rich Text)
作者 (Rich Text)
分数 (Number)
评论数 (Number)
发布时间 (Date)
采集时间 (Date)
最后更新时间 (Date) ← 新增，必需
Reddit链接 (URL)
影响力评分 (Number)
优先级 (Select)
```

## 日志输出示例

系统运行时会输出详细的更新统计信息：

```
Notion 同步完成:
  ✅ 成功: 8 个
    - 新建: 3 个
    - 更新: 5 个
  ⏭️ 跳过: 12 个 (无需更新)
  ❌ 失败: 0 个

帖子 abc123 需要更新: 分数 25 -> 85 (+60, 240.0%), 评论 5 -> 15 (+10, 200.0%)
帖子 abc123 需要更新页面内容（评论数变化）
页面属性更新成功: notion_page_id
页面内容更新成功: notion_page_id (评论数: 15)
```

## 测试更新机制

运行测试脚本来验证更新机制是否正常工作：

```bash
python test_update_mechanism.py
```

测试脚本会：
1. 创建一个测试帖子
2. 验证小幅度变化不会触发更新
3. 验证大幅度变化会触发更新
4. 验证热门帖子和热议帖子的特殊规则
5. 验证评论内容更新功能
6. 验证内容完整替换机制

## 优势

1. **避免重复**: 不会为同一个帖子创建多个 Notion 页面
2. **实时更新**: 能够跟踪帖子热度的变化
3. **智能判断**: 只有在显著变化时才更新，避免频繁的无意义更新
4. **配置灵活**: 所有阈值都可以通过环境变量配置
5. **统计详细**: 提供详细的更新统计信息
6. **评论同步**: 自动更新评论内容，跟踪讨论热度
7. **内容整洁**: 完整替换机制避免内容重复和混乱
8. **减少冗余**: 移除不必要的原始链接，保持页面简洁

## 注意事项

1. **数据库字段**: 确保 Notion 数据库包含 "Reddit ID" 和 "最后更新时间" 字段
2. **权限设置**: 确保 Notion 集成有读取和更新数据库的权限
3. **API 限制**: 更新操作会消耗 Notion API 调用次数
4. **数据一致性**: 系统会基于 Reddit ID 查找现有页面，确保数据唯一性

## 故障排除

如果更新机制不工作，请检查：

1. **配置**: 确认 `NOTION_ENABLE_UPDATE=true`
2. **字段**: 确认 Notion 数据库包含必需字段
3. **权限**: 确认集成有足够的权限
4. **日志**: 查看日志中的错误信息
5. **测试**: 运行测试脚本验证功能

```bash
# 检查配置
python -c "from config.settings import *; initialize_configs(); print(f'更新功能: {notion_config.enable_update}')"

# 运行测试
python test_update_mechanism.py
``` 