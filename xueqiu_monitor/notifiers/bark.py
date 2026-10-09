"""Bark。"""

from xueqiu_monitor.notifiers.base import TextChannel, code_ok, enabled, env, http_url, read_json, reject, request


class BarkNotifier(TextChannel):
    name = "Bark"

    def __init__(self, server: str, device_key: str, sound: str, group: str):
        super().__init__()
        self.server = server
        self.device_key = device_key
        self.sound = sound
        self.group = group

    def deliver(self, text: str, title: str) -> bool:
        payload = {"device_key": self.device_key, "title": title, "body": text}
        if self.sound:
            payload["sound"] = self.sound
        if self.group:
            payload["group"] = self.group
        resp = request("Bark", "POST", f"{self.server}/push", json=payload, timeout=self.timeout)
        return code_ok("Bark", read_json("Bark", resp), "code", 200)


def from_env(errors: list[str]) -> BarkNotifier | None:
    if not enabled("BARK_ENABLED"):
        return None
    device_key = env("BARK_DEVICE_KEY")
    if not device_key:
        reject(errors, "已启用 Bark，但未配置 BARK_DEVICE_KEY")
        return None
    server = http_url(errors, "BARK_SERVER", env("BARK_SERVER") or "https://api.day.app")
    if server is None:
        return None
    return BarkNotifier(server, device_key, env("BARK_SOUND"), env("BARK_GROUP"))
