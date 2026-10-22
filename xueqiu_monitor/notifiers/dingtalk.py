"""钉钉自定义机器人。无 secret 时不加签；有 DINGTALK_SECRET 时按官方 HMAC-SHA256 加签。"""

import base64
import hashlib
import hmac
import logging
import time
import urllib.parse

import requests

from xueqiu_monitor.notifiers.base import _in_cooldown, _mark_sent, enabled, env, reject

logger = logging.getLogger(__name__)


def sign(secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).digest()
    return urllib.parse.quote_plus(base64.b64encode(digest))


class DingTalkNotifier:
    """钉钉自定义机器人（无加签，或可选加签）。"""

    name = "钉钉"

    def __init__(self, webhook: str, at_all: bool = False, secret: str = ""):
        self.webhook = webhook
        self.at_all = at_all
        self.secret = secret
        self._last_send: dict[str, float] = {}

    def _url(self) -> str:
        if not self.secret:
            return self.webhook
        timestamp = str(round(time.time() * 1000))
        signed = sign(self.secret, timestamp)
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={timestamp}&sign={signed}"

    def _post(self, payload: dict) -> bool:
        try:
            resp = requests.post(
                self._url(),
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

    def send_markdown(self, title: str, content: str, cube_id: str = "", rb_id: str | int = "") -> bool:
        if _in_cooldown(self._last_send, cube_id, rb_id):
            logger.info(f"[{cube_id}] 钉钉冷却期内，跳过重复通知")
            return True
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": content},
            "at": {"isAtAll": self.at_all},
        }
        ok = self._post(payload)
        if ok:
            _mark_sent(self._last_send, cube_id, rb_id)
        return ok

    def send_text(self, content: str) -> bool:
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"isAtAll": self.at_all},
        }
        return self._post(payload)


def from_env(errors: list[str]) -> DingTalkNotifier | None:
    if not enabled("DINGTALK_ENABLED"):
        return None
    webhook = env("DINGTALK_WEBHOOK")
    if not webhook or "你的access_token" in webhook:
        reject(errors, "已启用钉钉，但未配置有效的 DINGTALK_WEBHOOK")
        return None
    return DingTalkNotifier(webhook, at_all=enabled("AT_ALL"), secret=env("DINGTALK_SECRET"))
