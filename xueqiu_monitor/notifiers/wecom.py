"""企业微信群机器人。"""

from xueqiu_monitor.notifiers.base import TextChannel, clip, code_ok, enabled, env, http_url, read_json, reject, request


class WecomNotifier(TextChannel):
    name = "企业微信"

    def __init__(self, webhook: str):
        super().__init__()
        self.webhook = webhook

    def deliver(self, text: str, title: str) -> bool:
        payload = {"msgtype": "markdown", "markdown": {"content": clip(text, 4096)}}
        resp = request("企业微信", "POST", self.webhook, json=payload, timeout=self.timeout)
        return code_ok("企业微信", read_json("企业微信", resp), "errcode", 0)


def from_env(errors: list[str]) -> WecomNotifier | None:
    if not enabled("WECOM_ENABLED"):
        return None
    webhook = env("WECOM_WEBHOOK")
    if not webhook:
        reject(errors, "已启用企业微信，但未配置 WECOM_WEBHOOK")
        return None
    url = http_url(errors, "WECOM_WEBHOOK", webhook)
    if url is None:
        return None
    return WecomNotifier(url)
