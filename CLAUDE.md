# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

雪球组合监控系统 — 监控雪球组合持仓变动，通过已启用的通知渠道发送。

**Core package `xueqiu_monitor/`:**
- `monitor.py` — 监控主循环，按交易时段决定等待间隔。入口是 `python -m xueqiu_monitor`
- `schedule.py` — 盘中、休市、收盘前加速的间隔
- `client.py` — 雪球 API 客户端（`XueQiuClient.get_current_positions`）
- `changes.py` — 调仓记录里的主动买卖（`changes_from_rebalancing`）
- `messages.py` — 通知正文（`build_markdown`）
- `cookies.py` — Cookie 过期时间与哈希
- `state.py` — `monitor_state.json` 读写
- `config.py` — 环境变量。`.env` 和默认状态文件在仓库根目录，不在包目录里
- `login.py` — Playwright 本机登录。入口是 `python -m xueqiu_monitor.login`
- `notifiers/` — 每个渠道一个模块，由 `build_notifier` 按开关组装

## Development Commands

### Setup
```bash
# Install dependencies
uv sync

# Get Xueqiu cookie (requires XUEQIU_ACCOUNT and XUEQIU_PASSWORD in .env)
uv run python -m xueqiu_monitor.login
```

### Run
```bash
# Start monitoring (reads .env for config)
uv run python -m xueqiu_monitor
```

### Test
```bash
# Run tests
uv run pytest

# Run single test
uv run pytest tests/test_change_detection.py -v
```

### Lint
```bash
ruff check
```

## Architecture

### API Fallback Chain

雪球接口有三级降级策略（`XueQiuClient.get_current_positions`）:

1. **Primary:** `/cubes/rebalancing/current.json` — 最新持仓
2. **Fallback v5:** `/v5/cube/rebalancing/current.json` — 备用接口（可能 404）
3. **Fallback history:** `/cubes/rebalancing/history.json` — 降级兜底

接口返回格式不统一，`get_current_positions` 统一为 `[{symbol, name, weight, prev_weight, price}]`。

### Cookie Management

- **Expiry detection:** 支持两种过期时间解析
  - `xq_id_token` JWT `exp` 字段（优先）
  - `xq_a_token` 尾部时间戳（兜底）
- **Expiry warning:** 过期前 24 小时通知一次
- **Auth failure:** HTTP 401，或响应明确要求登录时，通知一次并继续按间隔请求。单纯的 HTTP 403 会刷新风控 Cookie 后重试，不把登录票判死
- **Cookie hash:** 用 MD5 追踪 Cookie 变更，避免同一份失效 Cookie 重复通知

状态记录在 `monitor_state.json` 的 `_token` 字段：
```python
{
  "_token": {
    "hash": "...",           # Cookie MD5
    "expiry": 1234567890.0,  # 解析出的过期时间戳
    "notified_expiry": True, # 是否已发送过期预警
    "auth_failed": True,     # 是否已确认失效
    "notify_pending": False  # 失效通知是否发送失败（待重试）
  }
}
```

### Change Detection

**Deduplication strategy:**
1. **Rebalancing ID tracking:** 每个组合记录 `last_rb_id`，同一次调仓只推送一次
2. **60-second cooldown:** 每个组合每分钟最多推送一次（防止重启时重复）
3. **First sight baselines:** 没有 `last_rb_id` 时只记下当前最新调仓，不补发历史

变动检测逻辑（`changes_from_rebalancing`）只看调仓记录的 `rebalancing_histories`，不比较 `current.json` 的实时市值权重：
- `proactive: false` 的条目是行情漂移，忽略
- 起点用 `prev_weight_adjusted`（没有则用 `prev_weight`），终点用 `target_weight`
- **新增:** 起点为 0，目标仓位 > 0
- **卖出:** 目标仓位为 0
- **加仓/减仓:** `|target_weight - prev_weight_adjusted| >= WEIGHT_CHANGE_THRESHOLD`

### Notification Flow

`Notifier` 聚合所有启用的渠道，一次调用同时推送。未启用任何渠道时，视为发送成功（只记日志）。某个渠道启用了但缺凭证：记一条错误并跳过该渠道，不退出监控循环。一个渠道请求失败不会挡住其余渠道。

渠道和开关（默认都是 false）：

- 钉钉 `DINGTALK_ENABLED`：`DINGTALK_WEBHOOK`，可选 `DINGTALK_SECRET`（HMAC-SHA256 加签）、`AT_ALL`。无 secret 时仍是原来的无加签机器人
- Telegram `TELEGRAM_ENABLED`：`TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`
- 飞书自建应用 `FEISHU_ENABLED`：`FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_ID`，可选 `FEISHU_RECEIVE_ID_TYPE`、`FEISHU_MODE`
- 飞书群机器人 `FEISHU_WEBHOOK_ENABLED`：`FEISHU_WEBHOOK`，可选 `FEISHU_WEBHOOK_SECRET`。可以和自建应用同时开
- 企业微信 `WECOM_ENABLED`：`WECOM_WEBHOOK`
- Slack `SLACK_ENABLED`：`SLACK_WEBHOOK`
- Discord `DISCORD_ENABLED`：`DISCORD_WEBHOOK`
- 邮件 `SMTP_ENABLED`：`SMTP_HOST`、`SMTP_FROM`、`SMTP_TO`，可选 `SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_STARTTLS`、`SMTP_SSL`
- 通用 Webhook `HTTP_WEBHOOK_ENABLED`：`HTTP_WEBHOOK_URL`，可选 `HTTP_WEBHOOK_BEARER`、`HTTP_WEBHOOK_EXTRA`
- ntfy `NTFY_ENABLED`：`NTFY_TOPIC`，可选 `NTFY_SERVER`、`NTFY_TOKEN`、`NTFY_PRIORITY`
- Gotify `GOTIFY_ENABLED`：`GOTIFY_SERVER`、`GOTIFY_TOKEN`，可选 `GOTIFY_PRIORITY`
- Pushover `PUSHOVER_ENABLED`：`PUSHOVER_USER`、`PUSHOVER_TOKEN`，可选 `PUSHOVER_PRIORITY`
- Teams `TEAMS_ENABLED`：`TEAMS_WEBHOOK`
- Matrix `MATRIX_ENABLED`：`MATRIX_HOMESERVER`、`MATRIX_ROOM_ID`、`MATRIX_TOKEN`
- Server酱 `SERVERCHAN_ENABLED`：`SERVERCHAN_SENDKEY`
- PushPlus `PUSHPLUS_ENABLED`：`PUSHPLUS_TOKEN`，可选 `PUSHPLUS_TOPIC`、`PUSHPLUS_TEMPLATE`
- Bark `BARK_ENABLED`：`BARK_DEVICE_KEY`，可选 `BARK_SERVER`、`BARK_SOUND`、`BARK_GROUP`
- WxPusher `WXPUSHER_ENABLED`：`WXPUSHER_APP_TOKEN`，以及 `WXPUSHER_UIDS` 或 `WXPUSHER_TOPIC_IDS`
- PushDeer `PUSHDEER_ENABLED`：`PUSHDEER_PUSHKEY`，可选 `PUSHDEER_SERVER`

所有渠道共用 `notifiers/base.py` 里的 `_in_cooldown`（60 秒，按组合）。

### State Persistence

`monitor_state.json` 结构：
```json
{
  "_token": { ... },
  "ZH123456": {
    "positions": [...],
    "nav": {"name": "组合名称"},
    "last_rb_id": 12345,
    "last_check": "2026-05-30T12:34:56"
  }
}
```

- 重启不丢失持仓快照
- k3s 部署时挂载到 `/data/monitor_state.json`

## Configuration

`.env` required fields:
- `XUEQIU_COOKIE` — 雪球登录 Cookie（格式：`xq_a_token=...;u=...`）
- `MONITORED_CUBES` — 监控的组合代码，逗号分隔（如 `ZH123456,ZH654321`）

Optional:
- `CHECK_INTERVAL` (default: 300) — 交易时段检查间隔（秒）
- `TRADING_HOURS_ONLY` (default: true) — 休市和周末改用 `OFF_HOURS_INTERVAL`（默认 1800）。设为 false 则始终用 `CHECK_INTERVAL`
- `OFF_HOURS_INTERVAL` / `PRE_CLOSE_MINUTES` / `PRE_CLOSE_INTERVAL` / `MARKET_CLOSE` — 休市间隔、收盘前加速和下午收盘时间（默认 15:00）
- `WEIGHT_CHANGE_THRESHOLD` (default: 0) — 仓位变动阈值（百分点）。0 表示有变化就通知
- `STATE_FILE` (default: 仓库根目录 `monitor_state.json`；k3s 为 `/data/monitor_state.json`)
- 通知渠道开关默认 false，变量名见上面的 Notification Flow，模板在 `.env.example`
- `LOG_FILE` (default: `xueqiu_monitor.log`) — 日志文件路径。空字符串只输出到终端

## Deployment

镜像只由 GitHub Actions（`.github/workflows/docker-publish.yml`）构建并发布。推送到 `main` 或打 `v*` 标签时，工作流构建 `linux/amd64` 与 `linux/arm64`，推送到 `ghcr.io/<owner>/xueqiu_monitor`（metadata-action 会把 `github.repository` 转成小写）。登录、Cookie、Playwright 和 kubeconfig 不进 Actions，也不要加部署作业。

```bash
docker pull ghcr.io/zeroornull/xueqiu_monitor:latest
```

首次 GHCR 包可能是私有的，要在 GitHub Packages 里设为公开。工作流未完成或包未公开时，拉取会被拒绝，集群也拉不到。

### k3s

本机 `k3s/release.sh` 只把仓库根目录的 `.env` 写成 Secret，再 `kubectl apply` 清单。它不构建、不推送镜像。清单使用 `ghcr.io/zeroornull/xueqiu_monitor:latest`。`k3s/push.sh` 只提示镜像由 GitHub Actions 发布。`k3s/` 含本机集群细节，已 gitignore，不要提交。

```bash
k3s/release.sh
```

镜像运行监控主程序，登录仍在本机完成（`python -m xueqiu_monitor.login`）。持仓快照写在 `/data/monitor_state.json`。

## Important Notes

- **Cookie lifecycle:** `python -m xueqiu_monitor.login` 只在本机执行。镜像不安装 Playwright，容器里自动重登会直接放弃
- **Anti-bot handling:** 雪球首页访问会下发风控 Cookie（`_init_session`），只附上认证 Cookie 可能被拒
- **Auth cookies:** 只保留 `xq_a_token`, `u`, `xq_r_token`, `xq_id_token`, `xqat`, `xq_is_login`，其余风控 Cookie 由每次会话下发
- **Playwright profile:** 登录状态保存在 `.xueqiu-chrome/`，未过期时无需重新输入密码
- **Manual verification:** 雪球登录可能弹出图形或短信验证，无法完全无人值守
