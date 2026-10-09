"""Gotify application message。"""

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, http_url, optional_int, reject, request


class GotifyNotifier(TextChannel):
    name = "Gotify"

    def __init__(self, server: str, token: str, priority: int):
        super().__init__()
        self.server = server
        self.token = token
        self.priority = priority

    def deliver(self, text: str, title: str) -> bool:
        resp = request(
            "Gotify",
            "POST",
            f"{self.server}/message",
            headers={"X-Gotify-Key": self.token},
            json={"title": title, "message": text, "priority": self.priority},
            timeout=self.timeout,
        )
        return resp is not None


def from_env(errors: list[str]) -> GotifyNotifier | None:
    if not enabled("GOTIFY_ENABLED"):
        return None
    token = env("GOTIFY_TOKEN")
    raw = env("GOTIFY_SERVER")
    if not token or not raw:
        reject(errors, "已启用 Gotify，但 GOTIFY_SERVER 或 GOTIFY_TOKEN 未配置")
        return None
    server = http_url(errors, "GOTIFY_SERVER", raw)
    if server is None:
        return None
    priority = optional_int("GOTIFY_PRIORITY", 5)
    return GotifyNotifier(server, token, 5 if priority is None else priority)
