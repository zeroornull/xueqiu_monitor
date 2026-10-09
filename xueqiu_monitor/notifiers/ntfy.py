"""ntfy。"""

from urllib.parse import quote

from xueqiu_monitor.notifiers.base import TextChannel, clip, enabled, env, http_url, optional_int, reject, request


class NtfyNotifier(TextChannel):
    name = "ntfy"

    def __init__(self, server: str, topic: str, token: str, priority: int | None):
        super().__init__()
        self.server = server
        self.topic = topic
        self.token = token
        self.priority = priority

    def deliver(self, text: str, title: str) -> bool:
        headers = {"Title": title}
        if self.priority is not None:
            headers["Priority"] = str(self.priority)
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = request(
            "ntfy",
            "POST",
            f"{self.server}/{quote(self.topic, safe='')}",
            data=clip(text, 4000).encode(),
            headers=headers,
            timeout=self.timeout,
        )
        return resp is not None


def from_env(errors: list[str]) -> NtfyNotifier | None:
    if not enabled("NTFY_ENABLED"):
        return None
    topic = env("NTFY_TOPIC")
    if not topic:
        reject(errors, "已启用 ntfy，但未配置 NTFY_TOPIC")
        return None
    server = http_url(errors, "NTFY_SERVER", env("NTFY_SERVER") or "https://ntfy.sh")
    if server is None:
        return None
    return NtfyNotifier(server, topic, env("NTFY_TOKEN"), optional_int("NTFY_PRIORITY"))
