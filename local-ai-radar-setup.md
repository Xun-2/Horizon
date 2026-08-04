# 本地 AI 雷达安装说明

## 准备密钥与 ClawBot

1. 在 Aoligei 控制台创建 New API Token，只用于 `AOLIGEI_API_KEY`；不要填写 OpenAI 官方密钥、Aoligei 网站密码或登录会话。
2. 在 PushPlus 中完成 ClawBot 扫码绑定后，主动向 ClawBot 发送一条消息，并确认状态显示“已激活”。Horizon 只能检测 ClawBot 是否可投递，不能绕过这一激活要求。
3. 在 PushPlus 开发设置中启用开放接口。生成至少 32 位的随机 `secretKey`，将当前执行机的公网 IP 加入安全 IP；用户 Token 与 `secretKey` 必须分开保存。
4. 每 10 次交互或每 24 小时，主动与 ClawBot 对话一次以保持会话活跃。Horizon 可以检测未激活或失效状态，但不能替代该操作。
5. 创建 GitHub fine-grained PAT，仅授权 `Xun-2/Horizon`，并授予 `Actions: Read and write`、`Contents: Read and write` 及 `Pages: Read and write`。本机恢复脚本用它查询和触发云端工作流。
6. 不要把任何 Token 写入 Git、命令行参数、截图或聊天记录。

## 首次安装

在仓库根目录运行：

```powershell
Copy-Item data/config.local.example.json data/config.json
uv sync --extra dev
powershell -ExecutionPolicy Bypass -File scripts/setup_local_secrets.ps1
uv run python scripts/check_local_setup.py --offline
```

密钥脚本会以隐藏输入依次收集 Aoligei Token、PushPlus 用户 Token、PushPlus Open API `secretKey` 和 GitHub PAT，然后写入本机 `.env`。`.env` 与 `data/config.json` 已被 Git 忽略，不应提交。

## 联网验收

模型和信息源检查必须显式使用 `--online`：

```powershell
uv run python scripts/check_local_setup.py --online
```

`--test-pushplus` 只验证 ClawBot 绑定、发送和最终投递状态：

```powershell
uv run python scripts/check_local_setup.py --online --test-pushplus
```

完整投递探针会依次发布 Pages 健康页、确认公开 HTTP 200、发送包含链接的 ClawBot 文本并等待最终投递状态：

```powershell
uv run python scripts/check_local_setup.py --online --test-delivery
```

成功时会依次显示 Pages 公开、ClawBot 请求已接受和“ClawBot 已送达”。首次 Pages 发布可能需要数分钟。若公开页未出现，检查仓库 `Settings -> Pages` 是否使用 `gh-pages / root`，并确认 PAT 包含 Pages 写权限。

## 配置 GitHub Actions 云端日报

1. 打开 GitHub 仓库 `Xun-2/Horizon`。
2. 进入 `Settings -> Secrets and variables -> Actions`。
3. 在 `Repository secrets` 中只创建以下两项：

   - `AOLIGEI_API_KEY`：Aoligei 控制台签发的 New API Token。
   - `PUSHPLUS_TOKEN`：PushPlus 用户 Token。

4. 不要在 GitHub Actions 中创建 `PUSHPLUS_SECRET_KEY`。云端采用 `accepted` 确认，只检查 PushPlus HTTP 2xx、业务码 `200` 和非空回执，不调用 PushPlus Open API。
5. 编辑本机使用的 fine-grained PAT，确认它只授权 `Xun-2/Horizon`，且同时保留 `Actions: Read and write`、`Contents: Read and write`、`Pages: Read and write`。
6. 在代码合并并推送到默认分支 `main` 后，进入 `Actions -> Daily Horizon Summary`，可使用 `Run workflow` 做首次云端测试。定时工作流只有位于默认分支时才会运行。

不要把密钥填写到 workflow YAML、配置 JSON、命令行参数、截图、日志或聊天中。workflow 使用 `${{ github.token }}` 发布 Pages，不需要第三个长期 GitHub Secret。

## 云端确认与本地最终投递验证

GitHub Actions 的目标是确认 PushPlus 已接受一条 ClawBot 消息。云端成功不等于已经查询到最终状态 `2`，因此不要把云端运行结论描述为“最终送达”。

本机保留 `PUSHPLUS_SECRET_KEY` 和安全 IP 配置，可使用下面的命令调用 PushPlus Open API，验证 ClawBot 最终状态为 `2`：

```powershell
uv run python scripts/check_local_setup.py --online --test-delivery
```

正常输出应包含：

```text
Offline configuration check passed
GitHub Pages test page is public
ClawBot request accepted
ClawBot 已送达
Online checks passed
```

## 每日调度与补跑机制

GitHub Actions 每天北京时间 `07:22` 运行。它先查询当天运行历史：当天已有成功记录时跳过；否则运行 Horizon。首次失败会等待 120 秒后再尝试一次。

Windows 任务不再在本机重复运行完整 AI 流水线，而是查询同一个 GitHub Actions 工作流：

- 当天 `07:22` 之前登录：不提前运行。
- 当天 `07:22` 之后首次登录：若当天已经成功，则不重复；若失败或没有运行，则立即触发云端补跑；若仍有任务运行中，则先等待结果。
- 每天 `07:45` 再执行一次兜底检查。
- 计划任务和 wrapper 都采用 `IgnoreNew`/独占锁，避免本机同时发起两个恢复请求。

整个投递语义是“至少一次”（at-least-once）。如果 PushPlus 已接受消息但网络在返回回执前中断，重试可能极少造成一条重复消息；系统不承诺严格 exactly-once。

## 安装或更新 Windows 恢复任务

云端 workflow、两个 GitHub Secrets 和本机 PAT 权限都配置完成后，先预览计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -WhatIf
```

确认 JSON 中包含 `run_cloud_recovery.ps1`、`at logon` 和 `daily 07:45` 后，安装或覆盖恢复任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -ConfirmCloudWorkflowReady
```

查看任务是否启用、触发器和执行脚本：

```powershell
Get-ScheduledTask -TaskName HorizonLocalAIRadar | Format-List TaskName, State, Actions, Triggers
```

## 检查运行结果

- 云端运行记录：GitHub 仓库 `Actions -> Daily Horizon Summary`。
- 中文日报：`https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/zh.html`。
- 英文日报：`https://xun-2.github.io/Horizon/daily/YYYY-MM-DD/en.html`。
- Windows 恢复日志：`logs/cloud-recovery-*.log`。日志只记录恢复动作和错误类型，不应包含 Token。
- Windows 任务状态：`Get-ScheduledTask -TaskName HorizonLocalAIRadar`。

首次真实云端运行成功后，应确认中英文 Pages 都返回 HTTP 200，并且微信只收到一条同时包含两个链接的 ClawBot 消息。同一北京时间日期再次手动运行时，guard 应输出 `skip`，Horizon 步骤应跳过，也不应出现第二条微信消息。

## 卸载计划任务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1
```
