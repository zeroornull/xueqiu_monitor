"""通知渠道共用的开关、冷却和 HTTP 发送。"""

import logging
import os
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_COOLDOWN_SECONDS = 60


def enabled(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


def flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() == "true"


def env(name: str) -> str:
    return os.environ.get(name, "").strip()


def reject(errors: list[str], message: str) -> None:
    logger.error(message)
    errors.append(message)


def optional_int(name: str, default: int | None = None) -> int | None:
    raw = env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.error(f"{name} 不是整数，已忽略")
        return default


def http_url(errors: list[str], key: str, value: str) -> str | None:
    if value.startswith(("http://", "https://")):
        return value.rstrip("/")
    reject(errors, f"{key} 需要 http 或 https 地址")
    return None


def title_from(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip().lstrip(">").strip()
        if cleaned:
            return cleaned[:80]
    return "雪球组合变动"


def clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _cooldown_key(cube_id: str, rb_id: str | int = "") -> str:
    # 按组合和调仓 ID 去重。只按组合的话，同一轮后面的新调仓会被当成已经发过。
    if not cube_id:
        return ""
    return f"{cube_id}:{rb_id}"


def _in_cooldown(last_send: dict[str, float], cube_id: str, rb_id: str | int = "") -> bool:
    key = _cooldown_key(cube_id, rb_id)
    if not key:
        return False
    return time.time() - last_send.get(key, 0) < _COOLDOWN_SECONDS


def _mark_sent(last_send: dict[str, float], cube_id: str, rb_id: str | int = "") -> None:
    key = _cooldown_key(cube_id, rb_id)
    if key:
        last_send[key] = time.time()


def _host(url: str) -> str:
    return urlparse(url).netloc or "unknown"


def request(name: str, method: str, url: str, **kwargs) -> requests.Response | None:
    timeout = kwargs.pop("timeout", 10)
    try:
        resp = requests.request(method, url, timeout=timeout, **kwargs)
    except Exception as exc:
        logger.error(f"{name} 请求异常: {type(exc).__name__}")
        return None
    if not resp.ok:
        logger.error(f"{name} HTTP {resp.status_code} ({_host(url)})")
        return None
    return resp


def read_json(name: str, resp: requests.Response | None) -> dict | None:
    if resp is None:
        return None
    if not resp.content:
        return {}
    try:
        data = resp.json()
    except Exception:
        text = (resp.text or "").strip()
        if text == "ok":
            return {"ok": True}
        logger.error(f"{name} 响应不是 JSON")
        return None
    if not isinstance(data, dict):
        logger.error(f"{name} 响应格式异常")
        return None
    return data


def code_ok(name: str, data: dict | None, key: str, expected: int) -> bool:
    if data is None:
        return False
    if data.get(key) == expected:
        return True
    detail = data.get("msg") or data.get("message") or data.get("errmsg") or ""
    logger.error(f"{name} 发送失败: {data.get(key)} {detail}".rstrip())
    return False


class TextChannel:
    """启用开关在组装时处理。发送失败只记日志并返回 False。"""

    name = "通知"
    timeout = 10

    def __init__(self):
        self._last_send: dict[str, float] = {}

    def send(self, text: str, *, title: str = "", cube_id: str = "", rb_id: str | int = "") -> bool:
        if _in_cooldown(self._last_send, cube_id, rb_id):
            logger.info(f"[{cube_id}] {self.name} 冷却期内，跳过重复通知")
            return True
        try:
            ok = self.deliver(text, title or title_from(text))
        except Exception as exc:
            logger.error(f"{self.name} 请求异常: {type(exc).__name__}")
            return False
        if ok:
            _mark_sent(self._last_send, cube_id, rb_id)
        return bool(ok)

    def deliver(self, text: str, title: str) -> bool:
        raise NotImplementedError

    def send_markdown(self, title: str, content: str, cube_id: str = "", rb_id: str | int = "") -> bool:
        return self.send(content, title=title, cube_id=cube_id, rb_id=rb_id)

    def send_text(self, content: str) -> bool:
        return self.send(content, title=title_from(content))


class Notifier:
    """把已启用的渠道一起发出去。一个都没启用时只记日志，并视为发送成功。"""

    def __init__(self, channels: list):
        self.channels = channels

    def describe(self) -> str:
        if not self.channels:
            return "未启用"
        return "、".join(ch.name for ch in self.channels)

    def _fanout(self, method: str, *args) -> bool:
        if not self.channels:
            logger.info("未启用通知渠道，跳过发送")
            return True
        ok = True
        for channel in self.channels:
            try:
                sent = getattr(channel, method)(*args)
            except Exception as exc:
                logger.error(f"{getattr(channel, 'name', '通知')} 发送异常: {type(exc).__name__}")
                sent = False
            if not sent:
                ok = False
        return ok

    def send_markdown(self, title: str, content: str, cube_id: str = "", rb_id: str | int = "") -> bool:
        return self._fanout("send_markdown", title, content, cube_id, rb_id)

    def send_text(self, content: str) -> bool:
        return self._fanout("send_text", content)
