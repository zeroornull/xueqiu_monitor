"""Discord incoming webhook。"""

from xueqiu_monitor.notifiers.base import TextChannel, clip, enabled, env, http_url, reject, request


class DiscordNotifier(TextChannel):
    name = "Discord"

    def __init__(self, webhook: str):
        super().__init__()
        self.webhook = webhook

    def deliver(self, text: str, title: str) -> bool:
        resp = request(
            "Discord",
            "POST",
            self.webhook,
            json={"content": clip(text, 2000)},
            timeout=self.timeout,
        )
        return resp is not None


def from_env(errors: list[str]) -> DiscordNotifier | None:
    if not enabled("DISCORD_ENABLED"):
        return None
    webhook = env("DISCORD_WEBHOOK")
    if not webhook:
        reject(errors, "已启用 Discord，但未配置 DISCORD_WEBHOOK")
        return None
    url = http_url(errors, "DISCORD_WEBHOOK", webhook)
    if url is None:
        return None
    return DiscordNotifier(url)
