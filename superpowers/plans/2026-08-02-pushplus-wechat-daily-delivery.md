# PushPlus 微信每日推送 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 使用现有 PushPlus `overview` 好友式摘要和 Windows 计划任务，让 Horizon 每天 07:22 主动推送到已绑定的微信接收端。

**Architecture:** 不新增服务或消息平台。先用现有 `check_local_setup.py` 验证本地配置、模型/资讯源和真实 PushPlus 投递，再用 `install_scheduled_task.ps1` 注册调用 `run_horizon.ps1` 的每日任务，最后读取任务定义进行验收。

**Tech Stack:** PowerShell、Windows Task Scheduler、`uv`、Python `scripts/check_local_setup.py`、现有 PushPlus Webhook notifier。

## Global Constraints

- Webhook 必须使用 `platform: "pushplus"` 和 `delivery: "overview"`，不实现个人微信登录、私聊、入站指令或自动回复。
- AI 密钥只放在本地 `.env` 或受忽略的本地配置中，使用 `AOLIGEI_API_KEY`；PushPlus token 只放在 `PUSHPLUS_TOKEN` 对应的本地配置中。
- 任何检查、日志或验收输出不得显示密钥值、完整 Webhook URL 或敏感请求头。
- 只有 `check_local_setup.py --online --test-pushplus` 成功后，才允许注册计划任务。
- 任务固定为中国标准时间每天 `07:22`，最长运行两小时，重叠实例使用 `IgnoreNew`。
- 不暂存、修改或回滚工作区中与本任务无关的用户文件。

---

### Task 1: 验证本地配置与真实 PushPlus 投递

**Files:**
- Read: `data/config.json`
- Read: `.env`
- Test: `scripts/check_local_setup.py`

**Interfaces:**
- Consumes: `data/config.json` 中的 `ai`, `webhook` 配置和 `.env` 中的 `AOLIGEI_API_KEY`、`HORIZON_WEBHOOK_URL`、`PUSHPLUS_TOKEN`。
- Produces: 一个明确的通过/失败结果；只有通过结果才能进入 Task 2。

- [ ] **Step 1: 运行离线合同检查**

```powershell
uv run python scripts/check_local_setup.py --offline
```

Expected: 输出 `Offline configuration check passed`，且不输出任何密钥值。若输出 `Missing environment variable` 或合同错误，停止后续步骤，先修正本地 `.env`/`data/config.json`。

- [ ] **Step 2: 运行模型和资讯源联网检查，并发送一条真实 PushPlus 测试消息**

```powershell
uv run python scripts/check_local_setup.py --online --test-pushplus
```

Expected: 进程退出码为 `0`，输出 `Online checks passed`，并在已绑定的微信接收端看到标题为 `Horizon local setup test` 的测试消息。HTTP 403/404、模型探测失败、源探测失败或 PushPlus 投递失败都视为未通过，不能继续注册任务。

- [ ] **Step 3: 保存不含凭据的验证结果**

记录命令退出码、`Online checks passed` 是否出现，以及失败组件名称；不要复制 `.env`、完整 URL、请求体或响应中的 token。

### Task 2: 预览并注册每日 Windows 任务

**Files:**
- Read: `scripts/install_scheduled_task.ps1`
- Read: `scripts/run_horizon.ps1`
- Modify: Windows Task Scheduler task `HorizonLocalAIRadar`

**Interfaces:**
- Consumes: Task 1 的成功结果和仓库根目录中的 runner 脚本。
- Produces: 名为 `HorizonLocalAIRadar` 的每日计划任务，动作调用 `scripts/run_horizon.ps1`。

- [ ] **Step 1: 预览任务契约，不注册任务**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -WhatIf
```

Expected: 输出压缩 JSON，包含 `task_name` 为 `HorizonLocalAIRadar`、`schedule` 为 `daily 07:22`、`time_zone` 为 `China Standard Time`、工作目录为当前仓库根目录；系统任务列表不发生变化。

- [ ] **Step 2: 注册任务**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -ConfirmOnlineChecksPassed
```

Expected: 输出 `Scheduled task 'HorizonLocalAIRadar' registered.`。该命令不会立即运行 Horizon 或额外发送日报；它只注册每天 07:22 的任务。

- [ ] **Step 3: 确认注册命令未触及其他文件**

```powershell
git status --short
```

Expected: 只看到安装前已经存在的用户修改；不应出现被脚本意外暂存、覆盖或删除的项目文件。

### Task 3: 验收任务定义和运行安全设置

**Files:**
- Read: Windows Task Scheduler task `HorizonLocalAIRadar`
- Read: `scripts/run_horizon.ps1`

**Interfaces:**
- Consumes: Task 2 创建的任务定义。
- Produces: 可审计的任务配置结果和后续运行检查清单。

- [ ] **Step 1: 读取任务的关键字段**

```powershell
$task = Get-ScheduledTask -TaskName 'HorizonLocalAIRadar' -ErrorAction Stop
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    Trigger = ($task.Triggers | Select-Object -First 1 ScheduleType, StartBoundary, Enabled)
    Action = ($task.Actions | Select-Object -First 1 Execute, Arguments, WorkingDirectory)
    StartWhenAvailable = $task.Settings.StartWhenAvailable
    WakeToRun = $task.Settings.WakeToRun
    MultipleInstances = $task.Settings.MultipleInstances
    ExecutionTimeLimit = $task.Settings.ExecutionTimeLimit
}
```

Expected: 任务名为 `HorizonLocalAIRadar`；触发器是每天 07:22 且启用；动作指向 `powershell.exe` 和仓库中的 `scripts/run_horizon.ps1`；工作目录为仓库根目录；`StartWhenAvailable`、`WakeToRun` 为 `True`；`MultipleInstances` 为 `IgnoreNew`；执行时限为两小时。

- [ ] **Step 2: 检查 runner 的日志和互斥行为**

确认 `scripts/run_horizon.ps1` 创建 `logs/`、使用 `logs/horizon.lock` 防止并发，并把运行结果写入带时间戳的日志；不要为了验证而手动启动一次真实日报。

- [ ] **Step 3: 运行现有 PushPlus 回归测试**

```powershell
$env:PYTHONUTF8 = '1'
uv run python -m pytest -p no:cacheprovider -q tests/test_pushplus.py tests/test_summarizer.py
```

Expected: 所有选定测试通过。该回归测试验证 PushPlus 好友式摘要和脱敏逻辑没有被任务安装流程影响。

### Task 4: 交付运行说明

**Files:**
- Read: `docs/local-ai-radar-setup.md`
- Read: `docs/superpowers/specs/2026-08-01-pushplus-wechat-daily-delivery-design.md`

**Interfaces:**
- Consumes: Task 1-3 的命令输出和验收结果。
- Produces: 给用户的中文操作结果，包含任务名、时间、日志位置、测试结果和卸载命令。

- [ ] **Step 1: 汇总安装结果**

明确报告：真实 PushPlus 测试是否送达、任务是否注册、计划时间是否为中国标准时间 07:22、日志目录是否为 `logs/`。不得报告任何令牌值。

- [ ] **Step 2: 提供可逆的卸载命令**

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1
```

先用 `-WhatIf` 预览，再执行第二条命令移除 `HorizonLocalAIRadar`；卸载不会删除日报、日志或本地密钥文件。
