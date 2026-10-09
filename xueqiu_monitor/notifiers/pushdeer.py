"""PushDeer。"""

from xueqiu_monitor.notifiers.base import TextChannel, code_ok, enabled, env, http_url, read_json, reject, request


class PushDeerNotifier(TextChannel):
    name = "PushDeer"

    def __init__(self, server: str, pushkey: str):
        super().__init__()
        self.server = server
        self.pushkey = pushkey

    def deliver(self, text: str, title: str) -> bool:
        resp = request(
            "PushDeer",
            "POST",
            f"{self.server}/message/push",
            json={"pushkey": self.pushkey, "text": text, "type": "markdown"},
            timeout=self.timeout,
        )
        return code_ok("PushDeer", read_json("PushDeer", resp), "code", 0)


def from_env(errors: list[str]) -> PushDeerNotifier | None:
    if not enabled("PUSHDEER_ENABLED"):
        return None
    pushkey = env("PUSHDEER_PUSHKEY")
    if not pushkey:
        reject(errors, "已启用 PushDeer，但未配置 PUSHDEER_PUSHKEY")
        return None
    server = http_url(errors, "PUSHDEER_SERVER", env("PUSHDEER_SERVER") or "https://api2.pushdeer.com")
    if server is None:
        return None
    return PushDeerNotifier(server, pushkey)
