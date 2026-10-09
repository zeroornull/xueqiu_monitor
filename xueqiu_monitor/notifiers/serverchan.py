"""Server酱 Turbo（SCT sendkey）。"""

from urllib.parse import quote

from xueqiu_monitor.notifiers.base import TextChannel, clip, code_ok, enabled, env, read_json, reject, request


class ServerChanNotifier(TextChannel):
    name = "Server酱"

    def __init__(self, sendkey: str):
        super().__init__()
        self.sendkey = sendkey

    def deliver(self, text: str, title: str) -> bool:
        url = f"https://sctapi.ftqq.com/{quote(self.sendkey, safe='')}.send"
        resp = request(
            "Server酱",
            "POST",
            url,
            data={"title": clip(title, 32), "desp": text},
            timeout=self.timeout,
        )
        return code_ok("Server酱", read_json("Server酱", resp), "code", 0)


def from_env(errors: list[str]) -> ServerChanNotifier | None:
    if not enabled("SERVERCHAN_ENABLED"):
        return None
    sendkey = env("SERVERCHAN_SENDKEY")
    if not sendkey:
        reject(errors, "已启用 Server酱，但未配置 SERVERCHAN_SENDKEY")
        return None
    return ServerChanNotifier(sendkey)
