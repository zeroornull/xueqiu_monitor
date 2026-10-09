"""Matrix client-server send message。一次 PUT。"""

import time
from urllib.parse import quote

from xueqiu_monitor.notifiers.base import TextChannel, enabled, env, http_url, reject, request


class MatrixNotifier(TextChannel):
    name = "Matrix"

    def __init__(self, homeserver: str, room_id: str, token: str):
        super().__init__()
        self.homeserver = homeserver
        self.room_id = room_id
        self.token = token

    def deliver(self, text: str, title: str) -> bool:
        room = quote(self.room_id, safe="")
        url = f"{self.homeserver}/_matrix/client/v3/rooms/{room}/send/m.room.message/{time.time_ns()}"
        resp = request(
            "Matrix",
            "PUT",
            url,
            headers={"Authorization": f"Bearer {self.token}"},
            json={"msgtype": "m.text", "body": text},
            timeout=self.timeout,
        )
        return resp is not None


def from_env(errors: list[str]) -> MatrixNotifier | None:
    if not enabled("MATRIX_ENABLED"):
        return None
    homeserver = env("MATRIX_HOMESERVER")
    room_id = env("MATRIX_ROOM_ID")
    token = env("MATRIX_TOKEN")
    if not homeserver or not room_id or not token:
        reject(errors, "已启用 Matrix，但 MATRIX_HOMESERVER、MATRIX_ROOM_ID 或 MATRIX_TOKEN 未配置")
        return None
    url = http_url(errors, "MATRIX_HOMESERVER", homeserver)
    if url is None:
        return None
    return MatrixNotifier(url, room_id, token)
