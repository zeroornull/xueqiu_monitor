# 雪球组合监控 · 钉钉 / Telegram 通知

> 定时监控雪球组合持仓变动，有变动时通过已启用的渠道推送。渠道都可以不接。

**当前版本**：v2.1 | **更新时间**：2026-05-30

---

## 功能特性

- **自动轮询** — 内置定时循环，无需额外调度器
- **仓位变动检测** — 基于本地持久化的持仓快照对比，避免重复触发
- **三接口级联降级** — 主接口 → v5 备用 → history 降级，自动切换保障稳定
- **防重复推送（双重）** — 调仓记录 ID 比对 + 60 秒冷却期，重启也不重复
- **Token 过期预警** — 自动解析 token 过期时间，过期前 1 天经已启用的渠道提醒
- **多渠道通知** — 钉钉、Telegram、飞书，以及 Slack、Discord、邮件、企业微信等。各自用开关启用，可以只开一个，也可以都不开。钉钉支持 @所有人和可选加签。
- **状态持久化** — 本地 JSON 文件保存持仓快照，重启不丢失
- **零第三方依赖** — 纯 `requests`，不依赖 pysnowball

---

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

### 2. 配置 .env

复制 `.env.example` 为 `.env`，填写以下必填项：

```env
XUEQIU_COOKIE=xq_a_token=你的token;u=你的uid
MONITORED_CUBES=ZH123456

# 通知渠道，两个都可以关掉；要启用哪个就设为 true
DINGTALK_ENABLED=false
DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=你的access_token
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 3. 运行

```bash
uv run python -m xueqiu_monitor
```

---

## 配置说明

### 必填配置

| 配置项 | 说明 |
|--------|------|
| `XUEQIU_COOKIE` | 雪球登录 Cookie，登录后从 F12 → Network 获取 |
| `MONITORED_CUBES` | 要监控的组合代码，多个用逗号分隔 |

### 可选配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CHECK_INTERVAL` | 300 | 检查间隔（秒），5 分钟 |
| `WEIGHT_CHANGE_THRESHOLD` | 1.0 | 仓位变动阈值（%），超过才通知 |
| `DINGTALK_ENABLED` | false | 是否启用钉钉通知 |
| `DINGTALK_WEBHOOK` | 空 | 钉钉机器人 Webhook，仅在启用钉钉时必填 |
| `AT_ALL` | false | 钉钉是否 @所有人 |
| `TELEGRAM_ENABLED` | false | 是否启用 Telegram 通知 |
| `TELEGRAM_BOT_TOKEN` | 空 | Bot Token，仅在启用 Telegram 时必填 |
| `TELEGRAM_CHAT_ID` | 空 | 接收消息的 Chat ID，仅在启用 Telegram 时必填 |
| `LOG_FILE` | xueqiu_monitor.log | 日志文件路径 |

---

## Token 获取

### 雪球 Cookie

在 `.env` 里填写自己的雪球账号和密码，然后执行：

```bash
uv run python -m xueqiu_monitor.login
```

```env
XUEQIU_ACCOUNT=手机号或邮箱
XUEQIU_PASSWORD=登录密码
```

脚本会打开本机 Chrome，自动切到「账号密码登录」、填入并提交，成功后把 Cookie 写入 `.env`。登录状态保存在 `.xueqiu-chrome/`，Cookie 过期后重新运行同一条命令；浏览器会话还在时不会再要密码。

雪球经常在提交后弹出图形验证码或短信验证。这一步没法稳定地无人值守，窗口会留着，验证完就会继续保存 Cookie。密码只放在本地 `.env`，不要发到聊天里。

> 注意：Cookie 有时效性，脚本会在过期前 1 天通过已启用的通知渠道提醒。

### 钉钉 Webhook

1. 打开钉钉群 → 群设置 → 智能群助手 → 添加机器人
2. 选择「自定义」机器人
3. 安全设置选「关键词」，填入 `雪球`
4. 复制 Webhook URL 到 `DINGTALK_WEBHOOK`，并把 `DINGTALK_ENABLED` 设为 `true`

### Telegram

1. 在 Telegram 找 `@BotFather`，发送 `/newbot`，拿到 Bot Token，填入 `TELEGRAM_BOT_TOKEN`
2. 给机器人发一条消息，或把机器人拉进目标群
3. 浏览器打开 `https://api.telegram.org/bot<token>/getUpdates`，从返回里找到 `chat.id`，填入 `TELEGRAM_CHAT_ID`
4. 把 `TELEGRAM_ENABLED` 设为 `true`

所有渠道都保持关闭时，监控照常运行，只写日志、不推送。某个渠道开了但缺凭证，会记一条错误并跳过该渠道，监控循环继续。

## 通知渠道

每个渠道都是 `<NAME>_ENABLED=true` 才发送，凭证只在启用时必填。消息正文沿用监控生成的 Markdown；渠道自己的接口如果必须带标题，就用这段文字的第一行。

| 渠道 | 开关 | 凭证 |
|------|------|------|
| 钉钉自定义机器人 | `DINGTALK_ENABLED` | `DINGTALK_WEBHOOK`，可选 `DINGTALK_SECRET`（HMAC-SHA256 加签）、`AT_ALL` |
| Telegram | `TELEGRAM_ENABLED` | `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID` |
| 飞书自建应用 | `FEISHU_ENABLED` | `FEISHU_APP_ID`、`FEISHU_APP_SECRET`、`FEISHU_RECEIVE_ID`，可选 `FEISHU_RECEIVE_ID_TYPE`、`FEISHU_MODE` |
| 飞书群机器人 | `FEISHU_WEBHOOK_ENABLED` | `FEISHU_WEBHOOK`，可选 `FEISHU_WEBHOOK_SECRET` |
| 企业微信群机器人 | `WECOM_ENABLED` | `WECOM_WEBHOOK` |
| Slack | `SLACK_ENABLED` | `SLACK_WEBHOOK` |
| Discord | `DISCORD_ENABLED` | `DISCORD_WEBHOOK` |
| 邮件 | `SMTP_ENABLED` | `SMTP_HOST`、`SMTP_FROM`、`SMTP_TO`，可选 `SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_STARTTLS`、`SMTP_SSL` |
| 通用 Webhook | `HTTP_WEBHOOK_ENABLED` | `HTTP_WEBHOOK_URL`，可选 `HTTP_WEBHOOK_BEARER`、`HTTP_WEBHOOK_EXTRA` |
| ntfy | `NTFY_ENABLED` | `NTFY_TOPIC`，可选 `NTFY_SERVER`（默认 `https://ntfy.sh`）、`NTFY_TOKEN`、`NTFY_PRIORITY` |
| Gotify | `GOTIFY_ENABLED` | `GOTIFY_SERVER`、`GOTIFY_TOKEN`，可选 `GOTIFY_PRIORITY` |
| Pushover | `PUSHOVER_ENABLED` | `PUSHOVER_USER`、`PUSHOVER_TOKEN`，可选 `PUSHOVER_PRIORITY` |
| Teams | `TEAMS_ENABLED` | `TEAMS_WEBHOOK`（Workflow incoming webhook） |
| Matrix | `MATRIX_ENABLED` | `MATRIX_HOMESERVER`、`MATRIX_ROOM_ID`、`MATRIX_TOKEN` |
| Server酱 | `SERVERCHAN_ENABLED` | `SERVERCHAN_SENDKEY` |
| PushPlus | `PUSHPLUS_ENABLED` | `PUSHPLUS_TOKEN`，可选 `PUSHPLUS_TOPIC`、`PUSHPLUS_TEMPLATE` |
| Bark | `BARK_ENABLED` | `BARK_DEVICE_KEY`，可选 `BARK_SERVER`（默认 `https://api.day.app`）、`BARK_SOUND`、`BARK_GROUP` |
| WxPusher | `WXPUSHER_ENABLED` | `WXPUSHER_APP_TOKEN`，以及 `WXPUSHER_UIDS` 或 `WXPUSHER_TOPIC_IDS` |
| PushDeer | `PUSHDEER_ENABLED` | `PUSHDEER_PUSHKEY`，可选 `PUSHDEER_SERVER`（默认 `https://api2.pushdeer.com`） |

同一轮通知会发给所有已启用且配置完整的渠道。一个渠道超时或返回错误，其余渠道照常发送。

---

## 通知效果

### 持仓变动通知

```markdown
## 📈 组合名称 持仓变动
> 组合代码：ZH123456　｜　检测时间：04/28 23:30

### 📋 变动明细
- 📈 **加仓** 贵州茅台（SH600519）：25.0% → **28.5%**（+3.5%）  当前价 ¥1680.00
- 🔴 **卖出** 中国平安（SH601318）：清仓（原仓位 10.0%）
```

### Token 过期预警

```markdown
## ⚠️ 雪球 Cookie 即将过期

> 过期时间：**2026-06-15 14:30**
> 剩余：**12.5 小时**

请及时更新 `.env` 文件中的 `XUEQIU_COOKIE`，否则监控将失效。
```

---

## 文件结构

```
xueqiu_monitor/              # 仓库根目录
├── xueqiu_monitor/          # Python 包
│   ├── __main__.py          # python -m xueqiu_monitor
│   ├── monitor.py           # 定时循环
│   ├── client.py            # 雪球接口
│   ├── changes.py           # 调仓变动
│   ├── messages.py          # 通知正文
│   ├── cookies.py           # 登录票过期时间
│   ├── state.py             # monitor_state.json
│   ├── config.py            # 环境变量
│   ├── login.py             # 本机 Chrome 登录
│   └── notifiers/           # 各通知渠道
├── tests/
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
├── Dockerfile
└── .github/workflows/docker-publish.yml
```

本地生成、不提交：`.env`、`.xueqiu-chrome/`、`monitor_state.json`、`xueqiu_monitor.log`。本机的 `k3s/` 清单也不入库。

---

## 镜像

公开镜像只由 GitHub Actions（`.github/workflows/docker-publish.yml`）发布。推送到 `main` 或打 `v*` 标签后，工作流构建 `linux/amd64` 和 `linux/arm64`，并推送 `ghcr.io/zeroornull/xueqiu_monitor`。本机不构建、不推送镜像。

容器只跑监控。先在本机用 `uv run python -m xueqiu_monitor.login` 取得 Cookie，再通过环境变量或 env 文件传入 `XUEQIU_COOKIE` 和 `MONITORED_CUBES`。镜像不安装 Playwright，容器里不会打开浏览器登录。

首次创建的 GHCR 包可能仍是私有的，需要到 GitHub Packages 里把可见性设为公开。工作流还没跑完，或包仍是私有时，拉取会被拒绝。

```bash
docker pull ghcr.io/zeroornull/xueqiu_monitor:latest

docker run -d --name xueqiu-monitor \
  --env-file .env \
  -v xueqiu-monitor-data:/data \
  ghcr.io/zeroornull/xueqiu_monitor:latest
```

持仓快照写在卷里的 `/data/monitor_state.json`。

---

## 部署到 k3s

集群使用 `ghcr.io/zeroornull/xueqiu_monitor:latest`。镜像要等 Actions 发布完成，并且 GHCR 包已公开，集群才能拉下来。登录仍在本机完成。没有 Service 和 Ingress。

`k3s/release.sh` 只根据仓库根目录的 `.env` 更新 Secret，再应用清单。它不构建镜像。`k3s/push.sh` 不再构建或推送，只说明镜像由 GitHub Actions 发布。

```bash
k3s/release.sh
```

持仓快照写在卷里的 `/data/monitor_state.json`。改了 `.env` 之后执行 `k3s/release.sh`。

---

## 常见问题

**Q: Cookie 过期后会怎样？**  
A: `xq_id_token` 到期前 1 天会通知一次。接口返回 401，或响应明确要求登录时，会再通知一次，然后按检查间隔继续请求，持仓快照保持不变。单纯的 HTTP 403 会刷新风控 Cookie 后重试。同一份 Cookie 不会重复通知。更新 Cookie 后重启；k3s 上更新 `.env` 后执行 `k3s/release.sh`。

**Q: 报 403/401 错误？**  
A: Cookie 已失效或无效。重新执行 `uv run python -m xueqiu_monitor.login` 登录一次。

**Q: 报 404 错误？**  
A: 组合代码错误或组合不存在。请确认组合代码正确且为公开组合。

**Q: 持仓列表为空？**  
A: 可能是私密组合，或 Cookie 无权限访问该组合。

**Q: 通知没收到？**  
A: 检查钉钉群机器人关键词是否包含在消息中（关键词：雪球）。

**Q: 想同时监控多个组合？**  
A: 在 `MONITORED_CUBES` 中用逗号分隔即可：
```
MONITORED_CUBES=ZH123456,ZH654321,ZH111111
```

**Q: `xq_a_token` 没有下划线时间戳，能否提前预警？**  
A: 可以。脚本会尝试自动解析 token 值中的时间戳；如果格式不支持，会通过已有 403 检测实时告警，不影响正常监控。

---

## API 接口说明

| 优先级 | 接口 | 说明 |
|--------|------|------|
| 1 | `/cubes/rebalancing/current.json` | 最新持仓（主接口） |
| 2 | `/v5/cube/rebalancing/current.json` | v5 备用（可能 404） |
| 3 | `/cubes/rebalancing/history.json` | 调仓历史（降级兜底） |

---

## 停止监控

```bash
# 按 Ctrl+C 正常停止
```

---

## License

MIT