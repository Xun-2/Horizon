# PushPlus 好友式双语资讯推送设计

## 目标

将 Horizon 当前系统式的 PushPlus overview 改为更像懂技术的朋友主动分享资讯的双语摘要。每天分别发送一条中文消息和一条英文消息；每条消息突出前三条内容，并用一句话列出其余最多九条内容。

本功能必须保持克制、自然和专业，不使用虚假亲密称呼、夸张口语或过多表情。它只改变 PushPlus 的 overview 展示，不改变内容抓取、AI 分析、完整 Markdown 日报或其他 webhook 平台。

## 已确认决策

- 使用确定性的专用好友摘要渲染器，不增加额外 AI 调用。
- `webhook.languages` 同时包含 `zh` 和 `en` 时，每种语言各发送一条消息。
- 每条消息最多包含 12 条内容，其中前 3 条详细说明，其余最多 9 条一句话概括。
- 保留现有筛选和评分排序，但不在好友摘要中显示分数。
- 使用现有中英文 enrichment 产物，不把一种语言临时翻译成另一种语言。
- 不增加新的配置项。总量继续由现有 `digest.max_items` 控制，重点条数固定为 3。

## 非目标

- 不改变 Aoligei API 配置、模型、分析提示词或 enrichment 提示词。
- 不改变本地完整日报、邮件、飞书折叠卡片或非 PushPlus webhook 的输出。
- 不增加重试队列、定时任务或新的推送渠道。
- 不为缺失的事实或推荐理由调用 AI 补写内容。

## 用户可见行为

### 中文消息

消息标题为“今天这几条 AI 动态值得看”。正文先用一句自然开场说明当天入选数量，然后依次展示前三条：

1. 可点击的文章标题。
2. “发生了什么”：目标语言主摘要的首个完整句子。
3. “为什么值得看”：同一主摘要中随后一至两个完整句子。
4. 简洁来源名称和原文链接。

其余内容放在“另外几条，一句话看完”下，每条包含可点击标题、主摘要首个完整句子和来源。结尾使用“如果今天只读一条，我建议先看第 1 条。”

### 英文消息

消息标题为“A few AI updates worth your time today”。结构与中文一致，但所有说明文字和摘要均使用英文 artifact。结尾使用“If you only read one, start with the first.”

### 数量不足

- 只有 1 至 3 条时，全部按重点条目展示，不显示空的“另外几条”区段。
- 当天没有入选内容时，发送自然短消息，不显示阈值、模型或配置诊断建议。
- 渲染器对传入内容再执行最多 12 条的防御性限制，避免上游配置异常导致超长消息。

## 架构与组件

### `DailySummarizer`

新增纯渲染方法 `generate_friend_digest(items, date, total_fetched, language)`。该方法不访问网络、不调用模型，也不读取 webhook 配置，只负责把已经分析和本地化的 `ContentItem` 列表渲染成 Markdown。

渲染器复用现有 Markdown 转义、URL 校验和中文排版辅助函数。条目顺序严格保持传入顺序；上游 `apply_balanced_digest` 已按评分降序完成筛选和限额。

主摘要的选择顺序为：

1. 非空的目标语言 `ContentArtifact.lead`。
2. 目标语言 artifact 的第一个非空 block 内容。

目标语言 artifact 不存在或没有可用正文时，不回退到语言未明确的 `ContentAnalysis.summary`，只显示标题、来源和原文链接。

句子提取只在目标语言文本内进行，并保留完整句末标点。重点条目使用首句描述事件、随后一至两句说明价值；普通条目只使用首句。若文本不足以可靠拆分为两部分，则重点条目使用单一“重点”段落，不重复文本，也不推测缺失理由。

### `WebhookNotifier`

`build_daily_summary_messages` 保留现有语言过滤和发送数量控制。当同时满足以下条件时，overview 改用 `generate_friend_digest`：

- `platform == "pushplus"`
- `delivery == "overview"`

该分支同时设置好友式的中英文 `message_title`。非 PushPlus 平台继续调用 `generate_webhook_overview`，`summary`、`summary_and_items` 和飞书折叠卡片保持现有行为。

### 数据流

```text
抓取内容
  -> Aoligei 分析和中英文 enrichment
  -> 现有评分、去重、分组限额和排序
  -> PushPlus 好友摘要纯渲染
  -> 中文消息一条
  -> 英文消息一条
```

## 降级与错误处理

- 缺少目标语言 artifact 时不跨语言补齐；保留原始标题、来源和安全链接。
- 摘要为空或只有一个完整句子时，使用单一“重点”段落。
- 无效或不安全的 URL 通过现有 `_safe_url` 过滤，外部文本通过现有 Markdown 转义处理。
- PushPlus 的 HTTP 状态、业务码 `200` 校验、敏感值脱敏和 30 秒超时处理保持不变。
- 中文和英文分别构建与发送。单次发送失败按现有结果如实记录，不把失败报告为成功。

## 测试设计

### 摘要器单元测试

- 中文和英文分别读取对应 artifact。
- 12 条输入生成 3 条重点内容和 9 条一句话内容。
- 覆盖 0、1、2、3 条以及超过 12 条的边界。
- 输出顺序与输入的评分顺序一致。
- 缺少 artifact、空摘要和单句摘要不会产生跨语言内容、重复或异常。
- 无效 URL、Markdown 特殊字符和来源文本得到安全处理。

### Webhook 单元测试

- PushPlus `overview` 调用好友摘要并使用新标题。
- 中文和英文分别生成一条消息。
- 非 PushPlus `overview` 继续调用原 overview。
- 其他 delivery 模式和现有 PushPlus 业务码检查不回归。

### 验证

1. 运行好友摘要和 PushPlus 相关测试。
2. 运行完整测试套件。
3. 运行 `uv run python scripts/check_local_setup.py --online --test-pushplus`，确认 Aoligei、数据源和 PushPlus 通道均成功。
4. 执行一次真实双语日报推送，确认 PushPlus 对中文、英文各返回成功业务码；由用户核对手机上的最终排版和语气。

## 验收标准

- 每个启用的语言每天只收到一条 overview。
- 前三条能够快速说明事件和阅读价值，其余条目保持可扫描。
- 消息中不再出现“下面逐条发送详情”、评分列表或系统式诊断文案。
- 好友摘要不增加 Aoligei 请求次数，也不改变完整日报和其他 webhook 平台。
- 自动化测试、在线配置检查和真实 PushPlus 双语发送均成功。
