"""WxPusher。"""

from xueqiu_monitor.notifiers.base import TextChannel, clip, code_ok, enabled, env, read_json, reject, request


class WxPusherNotifier(TextChannel):
    name = "WxPusher"

    def __init__(self, app_token: str, uids: list[str], topic_ids: list[int]):
        super().__init__()
        self.app_token = app_token
        self.uids = uids
        self.topic_ids = topic_ids

    def deliver(self, text: str, title: str) -> bool:
        payload = {
            "appToken": self.app_token,
            "content": text,
            "summary": clip(title, 20),
            "contentType": 3,
            "uids": self.uids,
            "topicIds": self.topic_ids,
        }
        resp = request(
            "WxPusher",
            "POST",
            "https://wxpusher.zjiecode.com/api/send/message",
            json=payload,
            timeout=self.timeout,
        )
        return code_ok("WxPusher", read_json("WxPusher", resp), "code", 1000)


def from_env(errors: list[str]) -> WxPusherNotifier | None:
    if not enabled("WXPUSHER_ENABLED"):
        return None
    app_token = env("WXPUSHER_APP_TOKEN")
    uids = [item.strip() for item in env("WXPUSHER_UIDS").split(",") if item.strip()]
    topic_ids: list[int] = []
    for item in env("WXPUSHER_TOPIC_IDS").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            topic_ids.append(int(item))
        except ValueError:
            reject(errors, "WXPUSHER_TOPIC_IDS 里有不是整数的值")
            return None
    if not app_token or (not uids and not topic_ids):
        reject(errors, "已启用 WxPusher，但 WXPUSHER_APP_TOKEN 未配置，或 UID 和主题都为空")
        return None
    return WxPusherNotifier(app_token, uids, topic_ids)
