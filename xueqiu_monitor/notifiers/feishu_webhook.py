"""飞书群自定义机器人。与自建应用渠道互相独立。"""

import base64
import hashlib
import hmac
import logging
import time

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, http_url, reject, request
from xueqiu_monitor.notifiers.feishu import _markdown_to_feishu

logger = logging.getLogger(__name__)


def _sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


class FeishuWebhookNotifier(TextChannel):
    name = "飞书机器人"

    def __init__(self, webhook: str, secret: str = ""):
        super().__init__()
        self.webhook = webhook
        self.secret = secret

    def deliver(self, text: str, title: str) -> bool:
        payload: dict = {
            "msg_type": "interactive",
            "card": {
                "header": {"title": {"tag": "plain_text", "content": title}},
                "elements": [{"tag": "markdown", "content": _markdown_to_feishu(text)}],
            },
        }
        if self.secret:
            timestamp = str(int(time.time()))
            payload["timestamp"] = timestamp
            payload["sign"] = _sign(self.secret, timestamp)
        resp = request("飞书机器人", "POST", self.webhook, json=payload, timeout=self.timeout)
        if resp is None:
            return False
        try:
            data = resp.json()
        except Exception:
            return True
        if not isinstance(data, dict):
            return True
        code = data.get("code", data.get("StatusCode"))
        if code in (0, None):
            return True
        logger.error(f"飞书机器人发送失败: {code} {data.get('msg') or data.get('StatusMessage') or ''}".rstrip())
        return False


def from_env(errors: list[str]) -> FeishuWebhookNotifier | None:
    if not enabled("FEISHU_WEBHOOK_ENABLED"):
        return None
    webhook = env("FEISHU_WEBHOOK")
    if not webhook:
        reject(errors, "已启用飞书机器人，但未配置 FEISHU_WEBHOOK")
        return None
    url = http_url(errors, "FEISHU_WEBHOOK", webhook)
    if url is None:
        return None
    return FeishuWebhookNotifier(url, env("FEISHU_WEBHOOK_SECRET"))
