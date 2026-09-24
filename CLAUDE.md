# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

雪球组合监控系统 — 监控雪球组合持仓变动，通过钉钉/Telegram/飞书发送通知。

**Core files:**
- `xueqiu_monitor.py` — 监控主程序，内置定时循环，无需外部调度器
- `login.py` — 使用 Playwright 在本地 Chrome 中登录雪球并提取 Cookie
- `notifier.py` — 多渠道通知适配器（钉钉、Telegram、飞书），每个渠道可独立启用/禁用

## Development Commands

### Setup
```bash
# Install dependencies
uv sync

# Get Xueqiu cookie (requires XUEQIU_ACCOUNT and XUEQIU_PASSWORD in .env)
uv run python login.py
```

### Run
```bash
# Start monitoring (reads .env for config)
uv run python xueqiu_monitor.py
```

### Test
```bash
# Run tests
pytest

# Run single test
pytest tests/test_monitor.py::test_detect_changes -v
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
- **Auth failure:** 401/403 或响应要求登录时，通知并停止请求
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
3. **Snapshot comparison:** 对比上次保存的 `weight`（非 API 的 `prev_weight`），避免因接口数据不变而重复触发

变动检测逻辑（`detect_changes`）:
- **新增:** 上次快照不存在该 symbol
- **卖出:** 新快照不存在该 symbol
- **加仓/减仓:** `|new_weight - old_weight| >= WEIGHT_CHANGE_THRESHOLD`

### Notification Flow

`Notifier` 聚合所有启用的渠道，一次调用同时推送。未启用任何渠道时，视为发送成功（只记日志）。

**Channel implementations:**
- `DingTalkNotifier` — 无加签的自定义机器人
- `TelegramNotifier` — Bot API `sendMessage`，Markdown 转 HTML
- `FeishuNotifier` — 自建应用，卡片消息，长连接只用于事件订阅

所有渠道共享冷却期逻辑，由 `_in_cooldown` 统一控制。

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
- `CHECK_INTERVAL` (default: 300) — 检查间隔（秒）
- `WEIGHT_CHANGE_THRESHOLD` (default: 1.0) — 仓位变动阈值（%）
- `DINGTALK_ENABLED`, `TELEGRAM_ENABLED`, `FEISHU_ENABLED` (default: false) — 渠道开关
- `DINGTALK_WEBHOOK`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — 渠道凭证
- `FEISHU_APP_ID`, `FEISHU_APP_SECRET`, `FEISHU_RECEIVE_ID` — 飞书凭证
- `LOG_FILE` (default: `xueqiu_monitor.log`) — 日志文件路径

## Deployment

### k3s

```bash
# Login to registry
docker login gitea.173114.xyz

# Build, push, and deploy
k3s/release.sh

# Only build and push
k3s/push.sh

# Update config without rebuild
k3s/release.sh --skip-build
```

镜像运行监控主程序，登录仍在本机完成。持仓快照写在 `/data/monitor_state.json`。

## Important Notes

- **Cookie lifecycle:** `login.py` 只在本机执行，k3s 镜像不包含自动登录能力
- **Anti-bot handling:** 雪球首页访问会下发风控 Cookie（`_init_session`），只附上认证 Cookie 可能被拒
- **Auth cookies:** 只保留 `xq_a_token`, `u`, `xq_r_token`, `xq_id_token`, `xqat`, `xq_is_login`，其余风控 Cookie 由每次会话下发
- **Playwright profile:** 登录状态保存在 `.xueqiu-chrome/`，未过期时无需重新输入密码
- **Manual verification:** 雪球登录可能弹出图形或短信验证，无法完全无人值守
