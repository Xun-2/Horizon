# GitHub Actions 云端日报与本地补跑设计

**日期：** 2026-08-03
**状态：** 已确认
**适用仓库：** `Xun-2/Horizon`

## 1. 背景与目标

现有 Horizon 由 Windows 计划任务每天 07:22 在本机运行。任务使用
`Interactive` 登录类型；当电脑在计划时间关机或用户未登录时，任务会被记录为
错过，之后也不一定补跑。2026-08-03 的实际记录为 `NumberOfMissedRuns = 1`，
且当天没有生成 Horizon 日志。

本设计把 GitHub Actions 设为主执行器，使电脑关机时仍能生成和推送日报；本机
计划任务只承担云端状态检查与失败补发。系统需要满足：

- 每天北京时间 07:22 自动运行。
- 电脑关机不影响云端执行。
- 当天首次在 07:22 后登录 Windows 时，立即检查云端状态。
- 当天已经成功时不重复推送。
- 当天缺失或失败时立即触发同一个云端工作流补发。
- 每天只发送一条 ClawBot 消息，包含中文速览以及中英文 Pages 链接。
- 云端优先保证送达；极少数响应不确定的网络故障允许补发后出现重复消息。

## 2. 非目标

- 不让 GitHub-hosted runner 调用 PushPlus 开放接口或查询最终状态 `2`。
- 不尝试把 GitHub 动态出口 IP 加入 PushPlus 安全 IP。
- 不在 GitHub 中保存 `PUSHPLUS_SECRET_KEY`。
- 不保证分布式网络故障下的严格 exactly-once 语义。
- 不引入固定 IP 云主机、中转服务器或新的付费基础设施。

## 3. 方案比较与选择

### 3.1 GitHub Actions 运行记录作为共享状态，已选择

云端和本地都以同一工作流当天的运行状态作为成功依据。云端使用并发锁并在
启动前查重；本地通过 Actions API 查询状态，在缺失或失败时调用
`workflow_dispatch`。

优点：

- 不新增日报分支中的状态提交。
- 本地和云端共享同一个可信状态源。
- 可以区分成功、失败、排队和运行中状态。
- 本地不需要重新执行 AI、Pages 和 PushPlus 流程。

### 3.2 在 `gh-pages` 写成功标记文件，未选择

该方案状态直观，但会引入额外提交、并发写冲突和过期标记处理。

### 3.3 仅使用本地成功记录，未选择

电脑关机时本地无法观察云端状态，不能可靠防止云端与本地重复发送。

## 4. 总体架构

系统分为四个边界清晰的组件：

1. **云端日报工作流**
   - 由 `schedule` 和 `workflow_dispatch` 触发。
   - 负责当天查重、环境准备、有限重试和最终运行状态。

2. **Horizon 云端投递模式**
   - 使用 Aoligei 生成中英文日报。
   - 发布中英文 GitHub Pages 页面。
   - 发送一条包含两个页面链接的 ClawBot 纯文本消息。
   - 以 PushPlus 请求被接受作为云端投递成功。

3. **GitHub Actions 状态客户端**
   - 查询当天同一工作流的运行记录。
   - 排除当前工作流运行，识别当天已有成功。
   - 供本地恢复器查询和触发 `workflow_dispatch`。

4. **Windows 云端恢复器**
   - 不再直接执行 `uv run horizon`。
   - 在登录触发和 07:45 兜底触发时查询云端状态。
   - 成功时退出，运行中时等待，缺失或失败时触发补发。

## 5. 云端工作流

### 5.1 触发与时区

- GitHub Actions cron 使用 UTC。
- 北京时间 07:22 对应前一日 UTC 23:22，因此 cron 为 `22 23 * * *`。
- 同时启用 `workflow_dispatch`，供人工和本地恢复器补发。
- GitHub 计划任务可能延迟；业务日期统一按 `Asia/Shanghai` 计算。

### 5.2 权限与并发

工作流最小权限为：

- `actions: read`：查询当天同工作流运行记录。
- `contents: write`：发布 Pages 内容。
- `pages: write`：配置或更新 GitHub Pages。

工作流配置固定并发组 `horizon-daily`，`cancel-in-progress` 为 `false`。两个触发
同时发生时后一个进入队列。每个运行开始后再次查询当天成功记录；若已有成功，
则以成功状态无操作退出。

### 5.3 云端配置

新增独立的 GitHub Actions 配置文件，基于当前本地 Aoligei、信息源、双语 Pages
和 ClawBot 配置生成，不能继续使用旧 DeepSeek/飞书配置。

ClawBot 配置增加两个显式维度：

- `confirmation: accepted`：只要求 PushPlus `/send` 返回成功和非空消息回执。
- `message_mode: bilingual_links`：只发送一条中文速览与中英文 Pages 链接消息。

本地配置继续使用：

- `confirmation: delivered`：通过开放接口等待最终状态 `2`。
- `message_mode: bilingual_links`：与云端保持同一条消息的用户体验。

当 `confirmation` 为 `accepted` 时不要求 `secret_key_env`；当其为 `delivered` 时
必须要求有效的 `PUSHPLUS_SECRET_KEY`。

### 5.4 成功语义

一次云端日报只有同时满足以下条件才返回退出码 0：

1. Aoligei 成功生成所需内容。
2. 中英文 Pages 均发布成功并得到公开 URL。
3. 唯一一条 ClawBot 消息返回 HTTP 2xx、业务码 200 和非空消息回执。

现有编排器忽略 Pages 与 Webhook 投递结果，因此实现需要把结果聚合成明确的
每日投递结果，并在必需步骤失败时向 CLI 传播非零退出码。

### 5.5 重试语义

- 首次运行失败后等待约 2 分钟，再重试一次完整日报流程。
- 两次均失败时，工作流结论为失败。
- 本机恢复器发现失败后，可以再次触发一个新运行。
- 已有成功运行时，所有后续运行在发送前查重并退出。

用户选择“优先送达”。如果 PushPlus 已接收请求但响应在返回途中丢失，云端无法
确认实际状态，重试可能造成一条重复消息。该边界属于 at-least-once 语义，必须
在文档和日志中明确，不得宣称严格 exactly-once。

## 6. 单条 ClawBot 消息

消息使用 `channel=clawbot` 和 `template=txt`，包含：

- 当天日期与 Horizon 标题。
- 最多三条中文速览。
- 中文完整日报链接。
- 英文完整日报链接。

不把完整 Markdown 直接塞入 ClawBot。Pages 发布必须先于发送；任一页面没有
公开 URL 时不得把云端运行记录为成功。

## 7. 密钥与权限边界

GitHub Actions Secrets 只保存：

- `AOLIGEI_API_KEY`
- `PUSHPLUS_TOKEN`

工作流内的固定值：

- `HORIZON_WEBHOOK_URL=https://www.pushplus.plus/send`
- `HORIZON_GITHUB_TOKEN=${{ github.token }}`，由 GitHub 提供，不创建长期 PAT。

仅保留在本机 `.env`：

- `PUSHPLUS_SECRET_KEY`
- 本机使用的 `HORIZON_GITHUB_TOKEN`

本机 fine-grained PAT 在现有 `Contents: Read and write`、`Pages: Read and write`
之外，需要增加 `Actions: Read and write`，用于查询运行和触发工作流。

任何日志、测试输出和错误消息都不得打印 Token、secretKey、AccessKey 或 Aoligei
Key。日志只能显示变量名及 `SET/UNSET` 状态。

## 8. Windows 恢复器

### 8.1 触发器

原 `HorizonLocalAIRadar` 任务改为调用云端恢复脚本，触发器包括：

- 当前用户登录 Windows 时触发。
- 每天 07:45 触发一次兜底检查。

登录时间早于 07:22 时不提前生成日报；恢复器直接退出，等待云端 07:22 运行或
本地 07:45 检查。登录时间在 07:22 之后时立即检查云端。

### 8.2 状态处理

恢复器按北京时间当天零点计算查询窗口：

- **存在成功运行**：记录 no-op 并退出 0。
- **存在排队或运行中的运行**：轮询等待；成功则退出，失败则 dispatch。
- **只有失败或取消运行**：立即 dispatch。
- **当天无运行**：立即 dispatch。
- **GitHub API 暂时不可用**：返回非零并写入脱敏日志，不在本地直接发送。

恢复器触发 dispatch 后记录 GitHub 返回的运行请求结果，不等待整份日报完成超过
Windows 任务执行上限。

## 9. 测试设计

### 9.1 配置与客户端单元测试

- `accepted` 模式允许不配置 `PUSHPLUS_SECRET_KEY`。
- `delivered` 模式仍强制要求 `PUSHPLUS_SECRET_KEY`。
- 固定 `channel=clawbot`、`template=txt`。
- PushPlus HTTP 失败、业务码失败和缺少回执均返回失败。
- 所有错误路径均脱敏。

### 9.2 消息与流水线测试

- 中英文摘要只生成一条 `bilingual_links` 消息。
- 消息同时包含中英文页面 URL。
- Pages 发布发生在 PushPlus 发送之前。
- 模型、任一 Pages 发布或 PushPlus 接受失败都会传播非零结果。
- 成功结果只能在单条消息得到回执后产生。

### 9.3 工作流合同测试

- YAML 可以被结构化解析。
- cron 固定为 `22 23 * * *`。
- 同时包含 `workflow_dispatch`。
- 权限、并发组和 `cancel-in-progress: false` 正确。
- 工作流只引用允许的 GitHub Secrets。
- 失败后只进行一次有限重试，避免无限消耗模型额度。
- 当天已有成功运行时不执行 AI 或 PushPlus 步骤。

### 9.4 Windows 恢复器测试

使用模拟 GitHub API 覆盖：

- 07:22 前登录不 dispatch。
- 当天成功时 no-op。
- 排队或运行中时等待且不重复 dispatch。
- 运行中最终失败时 dispatch。
- 当天只有失败时 dispatch。
- 当天无记录时 dispatch。
- GitHub API 失败时脱敏退出。
- 安装脚本 `-WhatIf` 显示登录触发和 07:45 兜底，不再调用本地 Horizon 主流程。

## 10. 上线验收

1. 在 GitHub Actions Secrets 配置 Aoligei 与 PushPlus 用户 Token。
2. 为本机 PAT 增加 `Actions: Read and write`。
3. 将工作流合入并推送到默认分支 `main`。
4. 手动执行一次 `workflow_dispatch`。
5. 确认 Actions 运行成功、中英文 Pages 均返回 HTTP 200、微信收到一条消息。
6. 当天再次执行 `workflow_dispatch`，确认查重 no-op，微信没有第二条消息。
7. 模拟失败记录，运行本地恢复器，确认它触发补发而不在本机生成日报。
8. 重新注册 `HorizonLocalAIRadar`，核对登录触发与 07:45 触发器。
9. 保持电脑关机，次日确认 GitHub Actions 自动执行并收到一条 ClawBot 消息。

## 11. 验收标准

- 电脑关机时云端仍能在每日计划时间运行。
- 正常情况下每天只收到一条 ClawBot 消息。
- 消息提供中文速览和两个可在手机浏览的 Pages 链接。
- 当天已有成功运行时，本地登录和人工 dispatch 都不会再次发送。
- 当天云端缺失或失败时，07:22 后首次登录会触发补发。
- 云端不保存 PushPlus secretKey，且不依赖固定出口 IP。
- 所有自动化测试通过，真实云端首发与当天查重验收通过。
