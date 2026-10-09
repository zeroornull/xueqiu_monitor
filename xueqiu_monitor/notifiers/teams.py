"""Microsoft Teams Workflow incoming webhook（Adaptive Card）。"""

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, http_url, reject, request


class TeamsNotifier(TextChannel):
    name = "Teams"

    def __init__(self, webhook: str):
        super().__init__()
        self.webhook = webhook

    def deliver(self, text: str, title: str) -> bool:
        payload = {
            "type": "message",
            "attachments": [{
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": [{"type": "TextBlock", "text": text, "wrap": True}],
                },
            }],
        }
        resp = request("Teams", "POST", self.webhook, json=payload, timeout=self.timeout)
        return resp is not None


def from_env(errors: list[str]) -> TeamsNotifier | None:
    if not enabled("TEAMS_ENABLED"):
        return None
    webhook = env("TEAMS_WEBHOOK")
    if not webhook:
        reject(errors, "已启用 Teams，但未配置 TEAMS_WEBHOOK")
        return None
    url = http_url(errors, "TEAMS_WEBHOOK", webhook)
    if url is None:
        return None
    return TeamsNotifier(url)
