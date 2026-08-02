# ClawBot 与 GitHub Pages 每日推送设计

## 目标

Horizon 每天生成中英文 AI 日报后，将完整内容发布到公开 GitHub Pages，并通过 PushPlus 的微信 ClawBot 渠道发送纯文本速览和当天页面链接。手机用户可在微信气泡中快速扫描，再在微信内置浏览器中阅读完整日报。

## 范围

- 继续使用现有 Windows 计划任务和本地 Horizon 管线。
- PushPlus 请求必须显式使用 `channel: "clawbot"`，不回退到默认的微信公众号渠道。
- ClawBot 使用 `template: "txt"`；Markdown 只在 GitHub Pages 中渲染。
- 完整日报公开发布到 `Xun-2/Horizon` 的 `gh-pages` 分支。
- 不实现个人微信登录、联系人操作、入站机器人指令或绕过 ClawBot 官方会话限制的行为。

## 设计方向

这是面向个人手机阅读的编辑型日报改版，基于现有 Jekyll/Cayman 做定向演进，不引入 React 或新的前端框架。

- `DESIGN_VARIANCE: 5`：保留清晰结构，使用轻微非对称的信息层级。
- `MOTION_INTENSITY: 2`：静态优先，无装饰动画，适配微信内置浏览器。
- `VISUAL_DENSITY: 5`：采用已确认的 B“快速扫描”布局，在手机首屏比较多条资讯。
- 单一浅色主题和单一深绿色强调色。
- 不使用营销 Hero、嵌套卡片、渐变装饰、负字距或依赖 JavaScript 的核心阅读交互。

## 架构

```text
Horizon 生成中英文摘要
  -> 渲染移动端静态 HTML
  -> GitHub Contents API 受控更新 gh-pages
  -> 轮询公开页面直到 HTTP 200
  -> PushPlus 发送 channel=clawbot, template=txt
  -> 轮询 PushPlus 最终投递状态
```

发布器只读取当次生成的结构化条目和摘要，只写远端 `gh-pages` 分支。它不运行 `git add`、`git commit` 或 `git push`，不会接触本地工作区中的其他未提交文件。

## GitHub Pages 发布

### 页面地址

```text
https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/zh.html
https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/en.html
```

首页地址为 `https://xun-2.github.io/Horizon/`，按日期倒序列出已发布日报，并提供中英文入口。

### 首次初始化

当前仓库没有 `gh-pages` 分支，Pages 也未启用。首次运行需要：

1. 通过 GitHub API 从远端 `main` 创建 `gh-pages` 分支。
2. 写入首页、共享样式和首批中英文日报。
3. 尝试将 Pages 来源设置为 `gh-pages` 分支根目录。
4. 如果 Token 没有 Pages 管理权限，停止自动启用步骤并给出中文指引，让用户在仓库设置中手动选择一次 `gh-pages / root`。

### 凭据

新增本地环境变量 `HORIZON_GITHUB_TOKEN`。使用 GitHub 细粒度 PAT，只授权仓库 `Xun-2/Horizon`：

- 必需：`Contents: Read and write`。
- 自动启用 Pages 时需要：`Pages: Read and write`。

Token 仅保存在被 Git 忽略的 `.env` 中，不进入配置示例值、日志、预览、异常详情或提交历史。

### 更新行为

- 每次运行只更新当天的 `zh.html`、`en.html`、首页索引和共享样式。
- 使用 Contents API 的 SHA 并发控制，避免覆盖远端同时发生的更新。
- 每个文件更新均可重试；只有全部当天页面成功写入后才更新首页。
- 发布后轮询公开 URL，确认 HTTP 200 且页面日期和语言标记正确。

## 手机页面

### 信息结构

顶部只显示 `Horizon Daily`、日期、条目数和中英文切换。正文采用等密度快速扫描列表：

1. 左侧为两位序号。
2. 右侧依次显示标题、两句扫描摘要和“详情与原文”。
3. 完整摘要、背景、社区讨论和参考链接使用原生 `<details>` 展开。
4. 空日报显示“今天暂无达到阈值的动态”，仍生成稳定页面和首页入口。

### 响应式约束

- 正文最大宽度约 `680px`，手机左右边距 `18px`。
- 正文字号不小于 `16px`，行高约 `1.65`。
- 点击区域至少 `44px` 高；长标题和长 URL 可换行且不产生横向滚动。
- 条目主要通过留白和分隔线组织，不用重复卡片容器。
- 页面使用系统中文/西文字体栈，无外部字体、图片和运行时脚本依赖。
- 桌面端保持同一阅读层级，仅增加外围留白，不改为多栏。

## ClawBot 消息

每种配置语言发送一条独立纯文本消息。中文消息包含自然问候、最多三条“标题 + 一句结论”和当天中文页面链接；英文采用相同结构并链接英文页面。

PushPlus 请求体固定包含：

```json
{
  "token": "${PUSHPLUS_TOKEN}",
  "channel": "clawbot",
  "title": "#{message_title}",
  "content": "#{summary}",
  "template": "txt"
}
```

如果 Pages 发布失败，仍发送不含链接的纯文本速览，并在末尾写明完整日报暂未发布。不能为了送达而切换到 `wechat` 服务号。

## ClawBot 官方限制

安装检查和中文说明必须明确要求：

1. 在 PushPlus“个人中心 -> 渠道配置 -> 微信 ClawBot”完成扫码绑定。
2. 主动向 ClawBot 发送一条消息，并确认监听状态为“已激活”。
3. 每下发 10 次消息后重新主动发起一次对话。
4. 每隔 24 小时至少主动发起一次对话。

Horizon 只检测和报告这些状态，不能绕过微信或 PushPlus 的限制。

## 状态语义与错误处理

- PushPlus HTTP 2xx 且业务 `code=200` 只表示“请求已受理”，不表示 ClawBot 已送达。
- 保存 PushPlus 返回的消息流水号，并通过官方开放接口轮询最终状态。
- 只有最终状态为成功才记录“ClawBot 已送达”；失败、超时、未激活和会话额度限制分别给出明确、脱敏的错误。
- GitHub 发布失败不影响本地 Markdown 日报保存；ClawBot 失败不回滚已发布页面。
- Pages 成功但公开 URL 尚未可用时，在有限时间内重试；超时后按“未发布”降级，不发送死链接。
- 日志不得包含 GitHub PAT、PushPlus Token、完整鉴权 URL、敏感请求头或可复用的查询凭据。

### 实施前置验证

编写实现计划时，必须先根据 PushPlus 最新官方文档核实最终状态查询接口、所需凭据、状态字段、终态映射和调用频率。不能假定普通用户 Token 可以查询最终状态；如果官方没有提供当前账号可用的最终状态接口，真实验收应停止并明确报告能力缺口，不能把“请求已受理”记录成“ClawBot 已送达”。

## 配置检查

本地检查脚本增加以下合同验证：

- `webhook.platform == "pushplus"`。
- `webhook.delivery == "overview"`。
- 请求体包含 `channel: "clawbot"` 和 `template: "txt"`。
- `HORIZON_GITHUB_TOKEN`、`PUSHPLUS_TOKEN` 和 `HORIZON_WEBHOOK_URL` 已设置，但不显示值。
- GitHub 仓库、目标分支和 Pages 状态可访问。
- 真实测试按照“发布测试页 -> 公开 URL 200 -> ClawBot 测试消息 -> 最终状态”完成。

## 测试与验收

### 自动化测试

- 页面 URL、日期、语言切换和首页索引生成。
- B 快速扫描布局、HTML 转义、长标题、长 URL 和空日报。
- PushPlus 请求强制包含 `channel=clawbot`、`template=txt`，且无默认渠道回退。
- GitHub SHA 并发控制、重试、部分失败和首页最后更新。
- 发布失败时 ClawBot 消息不含死链接。
- PushPlus“请求已受理”与“最终送达”状态分离。
- GitHub/PushPlus 凭据在预览、日志和异常中均被脱敏。
- 所有外部接口在单元和集成测试中模拟，不真实发布或发送。

### 视觉验收

- 手机视口 `390x844` 和 `430x932`：无横向滚动，文字不重叠，点击区域和换行符合约束。
- 桌面视口 `1440x900`：正文保持约 `680px` 最大宽度，外围留白稳定。
- 检查中文、英文、空日报、超长标题和展开内容。

### 真实验收

1. 首次初始化 `gh-pages` 并启用 Pages。
2. 发布一份测试日报，确认中英文公开 URL 返回 200。
3. 发送一条指定 `channel=clawbot` 的测试消息。
4. 确认微信中的 ClawBot 私聊收到纯文本速览，点击链接可在微信内置浏览器打开对应语言页面。
5. 查询 PushPlus 最终状态，确认日志记录为“ClawBot 已送达”，而非仅“请求已受理”。

## 非目标

- 不把 Markdown 直接塞入 ClawBot 气泡并期待原生渲染。
- 不自动提交或推送本地 `main` 工作区。
- 不公开 `.env`、模型密钥、GitHub PAT 或 PushPlus Token。
- 不增加服务号作为 ClawBot 失败时的隐式回退。
- 不在本阶段实现入站对话命令或双向机器人。
