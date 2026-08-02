# PushPlus 微信每日推送设计

## 目标

使用已存在的 PushPlus 通道，将 Horizon 的好友式日报每日主动推送到用户在 PushPlus 中已绑定的微信接收端。此功能只做单向通知，不接入个人微信账号、联系人、收消息或自动回复能力。

## 选定方案

复用现有 Windows 计划任务安装脚本，不新增常驻服务或新的消息平台集成。

理由：项目已有 PushPlus `overview` 好友式摘要、真实测试发送、运行锁、日志和任务安装脚本。复用这些边界可保持配置简单，并避免个人微信非官方自动化带来的账号和安全风险。

## 配置与前提

1. 本地密钥文件或进程环境中设置 `AOLIGEI_API_KEY` 和 PushPlus Webhook URL；令牌不进入 Git、文档、日志或命令输出。
2. Webhook 配置必须启用，并设置 `platform: "pushplus"`、`delivery: "overview"`；启用中英文时分别发送对应语言的好友式摘要。
3. 用户的 PushPlus 接收通道已绑定微信，且 Windows 时区为 `China Standard Time`。

## 安装流程

1. 运行本地联网检查，并使用 `--test-pushplus` 发送一条真实测试消息，确认 AI、资讯源和 PushPlus 均可用。
2. 检查成功后，以 `-ConfirmOnlineChecksPassed` 调用 `scripts/install_scheduled_task.ps1`。
3. 脚本注册名为 `HorizonLocalAIRadar` 的 Windows 计划任务：每天 `07:22` 调用 `scripts/run_horizon.ps1`，工作目录为仓库根目录。
4. 安装完成后读取任务定义，核对名称、每日触发时间、工作目录和执行命令。安装本身不额外发送日报。

## 运行与失败处理

- `run_horizon.ps1` 负责运行 Horizon、保留日志并防止重叠执行。
- 任务允许错过后补跑、唤醒设备执行，最长运行两小时；重叠运行按 `IgnoreNew` 跳过新实例。
- PushPlus 发送或上游抓取失败时，错误写入现有日志路径；Webhook 层继续对 URL、请求体、响应内容和敏感请求头中的凭据脱敏。
- 未通过联网检查时，不执行任务注册。

## 验收标准

1. 真实 PushPlus 测试消息在已绑定的微信接收端可见，且不显示令牌。
2. `HorizonLocalAIRadar` 任务存在，触发器为每天 `07:22`（中国标准时间），动作指向仓库中的 `run_horizon.ps1`。
3. 下一次计划运行生成 Horizon 日报，并以 PushPlus `overview` 好友式格式推送；中英文都启用时收到两条分别对应的内容。
4. 失败日志可用于诊断，且其中不包含 PushPlus 或模型 API 凭据。

## 非目标

- 不实现个人微信扫码登录、好友私聊、入站指令或自动回复。
- 不修改 PushPlus 之外的消息平台。
- 不自动创建任务，除非用户明确确认安装。
