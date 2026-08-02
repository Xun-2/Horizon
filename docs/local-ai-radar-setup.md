# 本地 AI 雷达安装说明

## 准备密钥

1. 在 Aoligei 控制台创建 New API Token，只用于 `AOLIGEI_API_KEY`；不要填写 OpenAI 官方密钥、Aoligei 网站密码或登录会话。
2. 在 PushPlus 中启用 ClawBot，并确认已建立可投递的会话；在 Open API 页面取得用户 Token 和 `secretKey`，填写时注意 IP 白名单。PushPlus 仅使用 ClawBot，不回退到微信公众号。
3. 创建 GitHub fine-grained PAT，仅授权 `Xun-2/Horizon`，并授予 `Contents: Read and write` 及 `Pages: Read and write`。
4. 不要把任何 Token 写入 Git、命令行参数、截图或聊天记录。

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

首次 Pages 发布可能需要数分钟。若公开页未出现，检查仓库 `Settings -> Pages` 是否使用 `gh-pages / root`，并确认 PAT 包含 Pages 写权限。

## 每日运行

联网验收通过后，可先预览计划任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -WhatIf
```

确认后注册每天 `07:22` 的任务：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/install_scheduled_task.ps1 -ConfirmOnlineChecksPassed
```

任务运行日志保存在 `logs/`，中英文 Markdown 日报保存在 `data/summaries/`。任务执行后，ClawBot 会发送 Horizon 日报链接。

## 卸载计划任务

```powershell
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1 -WhatIf
powershell -ExecutionPolicy Bypass -File scripts/uninstall_scheduled_task.ps1
```
