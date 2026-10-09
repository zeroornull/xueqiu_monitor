"""飞书自建应用。长连接只用于事件订阅，发送走开放平台接口。"""

import json
import logging
import time

import requests

from xueqiu_monitor.notifiers.base import _in_cooldown, enabled, env, reject

logger = logging.getLogger(__name__)


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
    receive_id = env("FEISHU_RECEIVE_ID")
    receive_type = env("FEISHU_RECEIVE_ID_TYPE")
    if not receive_type:
        if receive_id.startswith("ou_"):
            receive_type = "open_id"
        elif receive_id.startswith("on_"):
            receive_type = "union_id"
        else:
            receive_type = "chat_id"
    return receive_id, receive_type


class FeishuNotifier:
    """飞书自建应用，以应用身份发消息。"""

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


def from_env(errors: list[str]) -> FeishuNotifier | None:
    if not enabled("FEISHU_ENABLED"):
        return None
    app_id = env("FEISHU_APP_ID")
    app_secret = env("FEISHU_APP_SECRET")
    receive_id, receive_type = _feishu_target()
    mode = env("FEISHU_MODE")
    if mode and mode != "websocket":
        reject(errors, "FEISHU_MODE 只支持 websocket")
        return None
    if not app_id or not app_secret or not receive_id:
        reject(errors, "已启用飞书，但 FEISHU_APP_ID、FEISHU_APP_SECRET 或 FEISHU_RECEIVE_ID 未配置")
        return None
    return FeishuNotifier(app_id, app_secret, receive_id, receive_type)
