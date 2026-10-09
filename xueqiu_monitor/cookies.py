"""登录票过期时间与 Cookie 哈希。不发请求。"""

import base64
import hashlib
import json
import re
from typing import Optional

from xueqiu_monitor import config


def _cookie_hash() -> str:
    return hashlib.md5(config.XUEQIU_COOKIE.encode()).hexdigest()


def _token_state(state: dict) -> dict:
    token_state = state.setdefault("_token", {})
    if token_state.get("hash") != _cookie_hash():
        token_state.clear()
        token_state["hash"] = _cookie_hash()
    return token_state


def _cookie_already_failed(state: dict) -> bool:
    token_state = state.get("_token") or {}
    return bool(token_state.get("auth_failed") and token_state.get("hash") == _cookie_hash())


def _jwt_payload(token: str) -> Optional[dict]:
    """读取 JWT 载荷，不校验签名。"""
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(payload))
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _jwt_expiry(token: str) -> Optional[float]:
    """读取 JWT 的 exp。xq_id_token 用这个字段表示过期时间。"""
    data = _jwt_payload(token)
    exp = data.get("exp") if data else None
    if isinstance(exp, (int, float)) and exp > 1_000_000_000:
        return float(exp)
    return None


def _is_user_id_token(token: Optional[str]) -> bool:
    """登录用户的 xq_id_token 中 uid 为正数。首页和风控页下发的是 uid=-1 的游客票。"""
    if not token:
        return False
    uid = (_jwt_payload(token) or {}).get("uid")
    return isinstance(uid, int) and not isinstance(uid, bool) and uid > 0


def _get_token_expiry(cookie: str) -> Optional[float]:
    """优先用 xq_id_token 的 exp，其次用 xq_a_token 末尾的时间戳。"""
    matched = re.search(r"xq_id_token=([^;]+)", cookie)
    if matched:
        expiry = _jwt_expiry(matched.group(1).strip().strip('"'))
        if expiry:
            return expiry
    matched = re.search(r"xq_a_token=([^;]+)", cookie)
    if not matched:
        return None
    token = matched.group(1).strip().strip('"')
    if "_" not in token:
        return None
    try:
        ts = int(token.rsplit("_", 1)[1])
    except ValueError:
        return None
    if ts > 1893456000:  # 超过秒级上限时按毫秒处理
        ts /= 1000
    if 1672531200 <= ts <= 1893456000:  # 2023 ~ 2030
        return float(ts)
    return None
