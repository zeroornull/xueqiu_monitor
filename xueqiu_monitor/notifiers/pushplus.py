"""PushPlus。"""

from xueqiu_monitor.notifiers.base import TextChannel, code_ok, enabled, env, read_json, reject, request


class PushPlusNotifier(TextChannel):
    name = "PushPlus"

    def __init__(self, token: str, topic: str, template: str):
        super().__init__()
        self.token = token
        self.topic = topic
        self.template = template

    def deliver(self, text: str, title: str) -> bool:
        payload = {
            "token": self.token,
            "title": title,
            "content": text,
            "template": self.template or "markdown",
        }
        if self.topic:
            payload["topic"] = self.topic
        resp = request("PushPlus", "POST", "https://www.pushplus.plus/send", json=payload, timeout=self.timeout)
        return code_ok("PushPlus", read_json("PushPlus", resp), "code", 200)


def from_env(errors: list[str]) -> PushPlusNotifier | None:
    if not enabled("PUSHPLUS_ENABLED"):
        return None
    token = env("PUSHPLUS_TOKEN")
    if not token:
        reject(errors, "已启用 PushPlus，但未配置 PUSHPLUS_TOKEN")
        return None
    return PushPlusNotifier(token, env("PUSHPLUS_TOPIC"), env("PUSHPLUS_TEMPLATE"))
