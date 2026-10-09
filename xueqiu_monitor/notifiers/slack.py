"""Slack incoming webhook。"""

import logging

from xueqiu_monitor.notifiers.base import TextChannel, clip, enabled, env, http_url, read_json, reject, request

logger = logging.getLogger(__name__)


class SlackNotifier(TextChannel):
    name = "Slack"

    def __init__(self, webhook: str):
        super().__init__()
        self.webhook = webhook

    def deliver(self, text: str, title: str) -> bool:
        resp = request("Slack", "POST", self.webhook, json={"text": clip(text, 40000)}, timeout=self.timeout)
        data = read_json("Slack", resp)
        if data is None:
            return False
        if data.get("ok") is False:
            logger.error(f"Slack 发送失败: {data.get('error') or '发送失败'}")
            return False
        return True


def from_env(errors: list[str]) -> SlackNotifier | None:
    if not enabled("SLACK_ENABLED"):
        return None
    webhook = env("SLACK_WEBHOOK")
    if not webhook:
        reject(errors, "已启用 Slack，但未配置 SLACK_WEBHOOK")
        return None
    url = http_url(errors, "SLACK_WEBHOOK", webhook)
    if url is None:
        return None
    return SlackNotifier(url)
