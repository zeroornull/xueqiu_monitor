"""Pushover messages API。"""

from xueqiu_monitor.notifiers.base import TextChannel, clip, code_ok, enabled, env, optional_int, read_json, reject, request


class PushoverNotifier(TextChannel):
    name = "Pushover"

    def __init__(self, user: str, token: str, priority: int | None):
        super().__init__()
        self.user = user
        self.token = token
        self.priority = priority

    def deliver(self, text: str, title: str) -> bool:
        payload = {
            "token": self.token,
            "user": self.user,
            "message": clip(text, 1024),
            "title": clip(title, 250),
        }
        if self.priority is not None:
            payload["priority"] = self.priority
        resp = request("Pushover", "POST", "https://api.pushover.net/1/messages.json", data=payload, timeout=self.timeout)
        return code_ok("Pushover", read_json("Pushover", resp), "status", 1)


def from_env(errors: list[str]) -> PushoverNotifier | None:
    if not enabled("PUSHOVER_ENABLED"):
        return None
    user = env("PUSHOVER_USER")
    token = env("PUSHOVER_TOKEN")
    if not user or not token:
        reject(errors, "已启用 Pushover，但 PUSHOVER_USER 或 PUSHOVER_TOKEN 未配置")
        return None
    return PushoverNotifier(user, token, optional_int("PUSHOVER_PRIORITY"))
