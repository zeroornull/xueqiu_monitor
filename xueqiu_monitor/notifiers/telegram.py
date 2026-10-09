"""Telegram Bot sendMessage。"""

import logging
import re
import time

import requests

from xueqiu_monitor.notifiers.base import _in_cooldown, enabled, env, reject

logger = logging.getLogger(__name__)


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


def from_env(errors: list[str]) -> TelegramNotifier | None:
    if not enabled("TELEGRAM_ENABLED"):
        return None
    token = env("TELEGRAM_BOT_TOKEN")
    chat_id = env("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        reject(errors, "已启用 Telegram，但 TELEGRAM_BOT_TOKEN 或 TELEGRAM_CHAT_ID 未配置")
        return None
    return TelegramNotifier(token, chat_id)
