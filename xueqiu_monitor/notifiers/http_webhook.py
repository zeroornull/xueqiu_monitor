"""通用 HTTP webhook。正文放在 text，标题放在 title，额外字段来自 JSON 对象。"""

import json

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, http_url, reject, request


class HttpWebhookNotifier(TextChannel):
    name = "Webhook"

    def __init__(self, url: str, bearer: str, extra: dict):
        super().__init__()
        self.url = url
        self.bearer = bearer
        self.extra = extra

    def deliver(self, text: str, title: str) -> bool:
        payload = dict(self.extra)
        payload["title"] = title
        payload["text"] = text
        headers = {"Authorization": f"Bearer {self.bearer}"} if self.bearer else None
        resp = request("Webhook", "POST", self.url, json=payload, headers=headers, timeout=self.timeout)
        return resp is not None


def from_env(errors: list[str]) -> HttpWebhookNotifier | None:
    if not enabled("HTTP_WEBHOOK_ENABLED"):
        return None
    raw = env("HTTP_WEBHOOK_URL")
    if not raw:
        reject(errors, "已启用 Webhook，但未配置 HTTP_WEBHOOK_URL")
        return None
    url = http_url(errors, "HTTP_WEBHOOK_URL", raw)
    if url is None:
        return None
    extra: dict = {}
    raw_extra = env("HTTP_WEBHOOK_EXTRA")
    if raw_extra:
        try:
            parsed = json.loads(raw_extra)
        except json.JSONDecodeError:
            reject(errors, "HTTP_WEBHOOK_EXTRA 不是合法 JSON")
            return None
        if not isinstance(parsed, dict):
            reject(errors, "HTTP_WEBHOOK_EXTRA 必须是 JSON 对象")
            return None
        extra = parsed
    return HttpWebhookNotifier(url, env("HTTP_WEBHOOK_BEARER"), extra)
