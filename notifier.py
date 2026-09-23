"""钉钉、Telegram 与飞书通知。每个渠道都由启用开关控制，可以都不开。"""

import json
import logging
import os
import re
import time

import requests

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 60


def _enabled(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def _in_cooldown(last_send: dict[str, float], cube_id: str) -> bool:
    if not cube_id:
        return False
    return time.time() - last_send.get(cube_id, 0) < _COOLDOWN_SECONDS


def _markdown_to_html(text: str) -> str:
    """把现有钉钉 Markdown 收成 Telegram HTML。"""
    lines = []
    for line in text.splitlines():
        heading = line.startswith("## ") or line.startswith("### ")
        if line.startswith("### "):
            line = line[4:]
        elif line.startswith("## "):
            line = line[3:]
        elif line.startswith("> "):
            line = line[2:]
        line = (
            line.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        line = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
        if heading:
            line = f"<b>{line}</b>"
        lines.append(line)
    html = "\n".join(lines)
    if len(html) > 4000:
        html = html[:4000] + "\n…"
    return html


class DingTalkNotifier:
    """钉钉自定义机器人（无加签）。"""

    name = "钉钉"

    def __init__(self, webhook: str, at_all: bool = False):
        self.webhook = webhook
        self.at_all = at_all
        self._last_send: dict[str, float] = {}

    def _post(self, payload: dict) -> bool:
        try:
            resp = requests.post(
                self.webhook,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            result = resp.json()
            if result.get("errcode") == 0:
                return True
            logger.error(f"钉钉发送失败: {result}")
            return False
        except Exception as e:
            logger.error(f"钉钉请求异常: {e}")
            return False

    def send_markdown(self, title: str, content: str, cube_id: str = "") -> bool:
        if _in_cooldown(self._last_send, cube_id):
            logger.info(f"[{cube_id}] 钉钉冷却期内，跳过重复通知")
            return True
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": content},
            "at": {"isAtAll": self.at_all},
        }
        ok = self._post(payload)
        if ok and cube_id:
            self._last_send[cube_id] = time.time()
        return ok

    def send_text(self, content: str) -> bool:
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"isAtAll": self.at_all},
        }
        return self._post(payload)


class TelegramNotifier:
    """Telegram Bot sendMessage。"""

    name = "Telegram"

    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id
        self._last_send: dict[str, float] = {}

    def _post(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
            result = resp.json()
            if result.get("ok"):
                return True
            logger.error(f"Telegram 发送失败: {result}")
            return False
        except Exception as e:
            logger.error(f"Telegram 请求异常: {type(e).__name__}")
            return False

    def send_markdown(self, _title: str, content: str, cube_id: str = "") -> bool:
        if _in_cooldown(self._last_send, cube_id):
            logger.info(f"[{cube_id}] Telegram 冷却期内，跳过重复通知")
            return True
        ok = self._post(_markdown_to_html(content))
        if ok and cube_id:
            self._last_send[cube_id] = time.time()
        return ok

    def send_text(self, content: str) -> bool:
        return self._post(_markdown_to_html(content))


class FeishuNotifier:
    """飞书自建应用，以应用身份发消息。长连接只用于事件订阅，发送走开放平台接口。"""

    name = "飞书"

    def __init__(self, app_id: str, app_secret: str, receive_id: str, receive_id_type: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.receive_id = receive_id
        self.receive_id_type = receive_id_type
        self._token = ""
        self._token_until = 0.0
        self._last_send: dict[str, float] = {}

    def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_until:
            return self._token
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10,
            )
            result = resp.json()
        except Exception as e:
            logger.error(f"飞书取 token 异常: {type(e).__name__}")
            return ""
        token = result.get("tenant_access_token") or ""
        if result.get("code") != 0 or not token:
            logger.error(f"飞书取 token 失败: {result.get('code')} {result.get('msg')}")
            return ""
        self._token = token
        self._token_until = now + max(60, int(result.get("expire") or 7200) - 120)
        return token

    def _post(self, msg_type: str, content: str) -> bool:
        token = self._access_token()
        if not token:
            return False
        try:
            resp = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/messages",
                params={"receive_id_type": self.receive_id_type},
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "receive_id": self.receive_id,
                    "msg_type": msg_type,
                    "content": content,
                },
                timeout=10,
            )
            result = resp.json()
        except Exception as e:
            logger.error(f"飞书请求异常: {type(e).__name__}")
            return False
        if result.get("code") == 0:
            return True
        logger.error(f"飞书发送失败: {result.get('code')} {result.get('msg')}")
        return False

    def send_markdown(self, title: str, content: str, cube_id: str = "") -> bool:
        if _in_cooldown(self._last_send, cube_id):
            logger.info(f"[{cube_id}] 飞书冷却期内，跳过重复通知")
            return True
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": "blue",
            },
            "elements": [{"tag": "markdown", "content": _markdown_to_feishu(content)}],
        }
        ok = self._post("interactive", json.dumps(card, ensure_ascii=False))
        if ok and cube_id:
            self._last_send[cube_id] = time.time()
        return ok

    def send_text(self, content: str) -> bool:
        body = json.dumps({"text": content}, ensure_ascii=False)
        return self._post("text", body)


def _markdown_to_feishu(text: str) -> str:
    """飞书卡片 Markdown 不支持标题语法，把标题收成加粗。"""
    lines = []
    for line in text.splitlines():
        if line.startswith("### "):
            line = f"**{line[4:]}**"
        elif line.startswith("## "):
            line = f"**{line[3:]}**"
        elif line.startswith("> "):
            line = line[2:]
        lines.append(line)
    rendered = "\n".join(lines)
    if len(rendered) > 4000:
        rendered = rendered[:4000] + "\n…"
    return rendered


def _feishu_target() -> tuple[str, str]:
    receive_id = os.environ.get("FEISHU_RECEIVE_ID", "").strip()
    receive_type = os.environ.get("FEISHU_RECEIVE_ID_TYPE", "").strip()
    if not receive_type:
        if receive_id.startswith("ou_"):
            receive_type = "open_id"
        elif receive_id.startswith("on_"):
            receive_type = "union_id"
        else:
            receive_type = "chat_id"
    return receive_id, receive_type


class Notifier:
    """把已启用的渠道一起发出去。一个都没启用时只记日志，并视为发送成功。"""

    def __init__(self, channels: list):
        self.channels = channels

    def describe(self) -> str:
        if not self.channels:
            return "未启用"
        return "、".join(ch.name for ch in self.channels)

    def send_markdown(self, title: str, content: str, cube_id: str = "") -> bool:
        if not self.channels:
            logger.info("未启用通知渠道，跳过发送")
            return True
        ok = True
        for channel in self.channels:
            if not channel.send_markdown(title, content, cube_id):
                ok = False
        return ok

    def send_text(self, content: str) -> bool:
        if not self.channels:
            logger.info("未启用通知渠道，跳过发送")
            return True
        ok = True
        for channel in self.channels:
            if not channel.send_text(content):
                ok = False
        return ok


def build_notifier() -> tuple[Notifier, list[str]]:
    """按启用开关组装通知器。启用了但缺凭证时返回错误，不启用则忽略凭证。"""
    channels = []
    errors = []

    if _enabled("DINGTALK_ENABLED"):
        webhook = os.environ.get("DINGTALK_WEBHOOK", "").strip()
        if not webhook or "你的access_token" in webhook:
            errors.append("已启用钉钉，但未配置有效的 DINGTALK_WEBHOOK")
        else:
            channels.append(DingTalkNotifier(webhook, at_all=_enabled("AT_ALL")))

    if _enabled("TELEGRAM_ENABLED"):
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        if not token or not chat_id:
            errors.append("已启用 Telegram，但 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置")
        else:
            channels.append(TelegramNotifier(token, chat_id))

    if _enabled("FEISHU_ENABLED"):
        app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        receive_id, receive_type = _feishu_target()
        mode = os.environ.get("FEISHU_MODE", "").strip()
        if mode and mode != "websocket":
            errors.append("FEISHU_MODE 只支持 websocket")
        elif not app_id or not app_secret or not receive_id:
            errors.append("已启用飞书，但 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID 未配置")
        else:
            channels.append(FeishuNotifier(app_id, app_secret, receive_id, receive_type))

    return Notifier(channels), errors
