#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
雪球组合变动监控 v2.1
──────────────────────────────────────
功能：
  · 定时拉取雪球组合持仓数据
  · 检测持仓新增/卖出/加减仓（按仓位权重对比）
  · 有变动时通过已启用的钉钉、Telegram 或飞书发送通知（也可以都不启用）
  · 记录上次调仓记录 ID，同一次调仓只推送一次（防重复）

依赖安装：
    uv sync

Token 获取方式：
    uv run python login.py
  在打开的 Chrome 里登录雪球，Cookie 会自动写入 .env。
"""

import json
import os
import re
import sys
import time
import atexit
import base64
import logging
import hashlib
import traceback
from datetime import datetime
from typing import Optional, Any

import requests

from notifier import Notifier, build_notifier

# ─────────────────────────────────────────────
#  尝试加载 .env（可选，有 python-dotenv 才生效）
# ─────────────────────────────────────────────
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(_env_path):
        load_dotenv(_env_path)
except ImportError:
    pass  # python-dotenv 未安装时直接读环境变量或使用下方硬编码配置

# ══════════════════════════════════════════════════════════════════
#  ⚙️  配置区（优先读取 .env，其次使用下方默认值）
# ══════════════════════════════════════════════════════════════════

# 雪球登录 Cookie（必填）
# .env 写法：XUEQIU_COOKIE=xq_a_token=xxx; u=xxxxxxxxxx
XUEQIU_COOKIE: str = os.environ.get(
    "XUEQIU_COOKIE",
    "xq_a_token=你的token;u=你的uid"   # ← 直接改这里，或用 .env
)

# 监控的雪球组合代码列表（必填）
# 多个组合用英文逗号分隔，如 "ZH123456,ZH654321"
_cubes_env = os.environ.get("MONITORED_CUBES", "")
MONITORED_CUBES: list[str] = (
    [c.strip() for c in _cubes_env.split(",") if c.strip()]
    if _cubes_env
    else ["ZH123456"]  # ← 直接改这里
)

# 检查间隔（秒），默认 5 分钟
CHECK_INTERVAL: int = int(os.environ.get("CHECK_INTERVAL", "300"))

# 仓位权重变动阈值（百分点），超过此值才触发通知，默认 1%
WEIGHT_CHANGE_THRESHOLD: float = float(os.environ.get("WEIGHT_CHANGE_THRESHOLD", "1.0"))

# 日志文件（空字符串=只输出到终端）
LOG_FILE: str = os.environ.get("LOG_FILE", "xueqiu_monitor.log")

# ══════════════════════════════════════════════════════════════════
#  📋  日志
# ══════════════════════════════════════════════════════════════════
_handlers = [logging.StreamHandler(sys.stdout)]
if LOG_FILE:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════
#  🌐  雪球 API 客户端
# ══════════════════════════════════════════════════════════════════
_BASE_URL   = "https://xueqiu.com"
_STOCK_BASE = "https://stock.xueqiu.com"
# 只带登录态。浏览器里的 acw_tc、ssxmod_itna 绑在原浏览器上，重放会得到 400/403。
_AUTH_COOKIE_NAMES = ("xq_a_token", "u", "xq_id_token", "xq_r_token", "xqat", "xq_is_login")
_WAF_COOKIE_NAMES = ("acw_tc", "acw_sc__v2", "ssxmod_itna", "ssxmod_itna2")


class CookieExpired(Exception):
    """当前 Cookie 已被雪球拒绝，或本地解析出的过期时间已到。"""


def _cookie_hash() -> str:
    return hashlib.md5(XUEQIU_COOKIE.encode()).hexdigest()


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


def _cookie_renew_hint() -> str:
    return (
        "请重新登录后更新 Cookie：\n"
        "- 本机执行 `uv run python login.py`\n"
        "- k3s 更新 `.env` 后执行 `k3s/release.sh --skip-build`"
    )


def _check_token_expiry(state: dict, notifier: Notifier) -> bool:
    """过期前 1 天提醒一次。返回 True 表示 state 已变更。"""
    token_state = _token_state(state)
    expiry = _get_token_expiry(XUEQIU_COOKIE)
    if expiry is None:
        return False

    token_state["expiry"] = expiry
    remaining_hours = (expiry - time.time()) / 3600
    if remaining_hours <= 0 or remaining_hours > 24 or token_state.get("notified_expiry"):
        return False

    logger.warning(f"雪球 Cookie 将在 {remaining_hours:.1f} 小时后过期")
    content = (
        f"## ⚠️ 雪球 Cookie 即将过期\n\n"
        f"> 过期时间：**{datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')}**\n"
        f"> 剩余：**{remaining_hours:.1f} 小时**\n\n"
        f"{_cookie_renew_hint()}"
    )
    if notifier.send_markdown("雪球 Cookie 即将过期", content):
        token_state["notified_expiry"] = True
    return True


def _install_cookie(client, header: str) -> None:
    global XUEQIU_COOKIE
    from login import _ENV_PATH, upsert_env

    upsert_env(_ENV_PATH, "XUEQIU_COOKIE", header)
    XUEQIU_COOKIE = header
    client.replace_auth_cookie(header)


def _profile_cookie() -> str | None:
    try:
        from login import _PROFILE_DIR, profile_cookie_header
    except ImportError:
        return None
    return profile_cookie_header(_PROFILE_DIR)


def _adopt_profile_cookie(client) -> bool:
    """Chrome 配置里有更新的登录票时直接换上，不打开窗口。"""
    header = _profile_cookie()
    if not header or header == XUEQIU_COOKIE:
        return False
    new_expiry = _get_token_expiry(header) or 0
    old_expiry = _get_token_expiry(XUEQIU_COOKIE) or 0
    if old_expiry and new_expiry <= old_expiry:
        return False
    _install_cookie(client, header)
    logger.info("已从本机 Chrome 配置读取登录 Cookie")
    return True


def _attempt_relogin(client) -> str:
    """ok / sms / failed / unavailable。成功时写回 .env 并换上新 Cookie。"""
    if _adopt_profile_cookie(client):
        return "ok"
    try:
        from login import acquire_cookie
    except ImportError:
        logger.error("无法自动登录：当前环境没有 login.py")
        return "unavailable"
    logger.warning("Chrome 配置里没有更新的登录态，尝试打开浏览器重新登录")
    result = acquire_cookie(interactive=False, current=XUEQIU_COOKIE)
    if result.status == "ok" and result.cookie and result.cookie != XUEQIU_COOKIE:
        _install_cookie(client, result.cookie)
        logger.info("重新登录成功，已更新 Cookie")
        return "ok"
    if result.status == "sms":
        logger.error("自动登录遇到短信验证，已放弃")
        return "sms"
    logger.error(f"自动重新登录未成功：{result.message or result.status}")
    return "failed" if result.status != "unavailable" else "unavailable"


def _fail_cookie(state: dict, notifier: Notifier, client, reason: str) -> bool:
    """本机若能换到更新的登录票就立刻重试。换不到也继续按间隔请求，不退出。"""
    if not client.relogin_tried:
        client.relogin_tried = True
        if _attempt_relogin(client) == "ok":
            return True
    _stop_for_cookie(state, notifier, reason)
    return False


def _stop_for_cookie(state: dict, notifier: Notifier, reason: str) -> None:
    """通知一次。进程继续按间隔请求，不把这份 Cookie 判死。"""
    token_state = _token_state(state)
    expiry = _get_token_expiry(XUEQIU_COOKIE)
    until = ""
    if expiry:
        until = f"\n> 登录票标注到期：**{datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')}**"
    logger.warning(f"雪球请求被拒绝，下一轮继续：{reason}")
    if token_state.get("auth_notified") and not token_state.get("notify_pending"):
        return
    content = (
        f"## ⚠️ 雪球请求被拒绝\n\n"
        f"> 原因：{reason}{until}\n\n"
        f"监控保持运行，按检查间隔继续请求。\n"
        f"这份登录票由雪球签发，有效期大约 30 天，到期前不用重新登录。\n"
    )
    sent = notifier.send_markdown("雪球请求被拒绝", content)
    token_state["auth_notified"] = bool(sent)
    token_state["notify_pending"] = not sent
    if not sent:
        logger.error("请求失败通知没发出去，下一轮再试一次")
    _save_state(state)


class XueQiuClient:
    """
    雪球组合数据客户端（2025/2026 有效版）
    接口优先级：
      1. /cubes/rebalancing/current.json  （最新持仓，推荐）
      2. /v5/cube/rebalancing/current.json（备用，可能 404）
      3. /cubes/rebalancing/history.json  （降级方案）
    """

    def __init__(self, cookie: str, portfolio_id: str):
        self.portfolio_id = portfolio_id.upper()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Referer": "https://xueqiu.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        self._init_session()
        self._apply_auth_cookies(cookie)
        self.login_cookie = cookie
        self.last_fetch_ok = False
        self.relogin_tried = False
        atexit.register(self.session.close)

    def _auth_cookie_values(self) -> dict[str, str]:
        found: dict[str, str] = {}
        for name in _AUTH_COOKIE_NAMES:
            value = self.session.cookies.get(name)
            if value:
                found[name] = value
        return found

    def _restore_user_cookies(self, previous: dict[str, str]) -> None:
        """风控页会用游客票覆盖登录态。已有用户票时丢掉这次下发的游客票。"""
        if not _is_user_id_token(previous.get("xq_id_token")):
            return
        if _is_user_id_token(self.session.cookies.get("xq_id_token")):
            return
        for cookie in list(self.session.cookies):
            if cookie.name in _AUTH_COOKIE_NAMES:
                self.session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        for name, value in previous.items():
            self.session.cookies.set(name, value, domain=".xueqiu.com", path="/")

    def _apply_auth_cookies(self, cookie: str) -> None:
        parsed: dict[str, str] = {}
        for item in cookie.split(";"):
            item = item.strip()
            if "=" not in item:
                continue
            name, value = item.split("=", 1)
            parsed[name.strip()] = value.strip().strip('"')
        for name in _AUTH_COOKIE_NAMES:
            if parsed.get(name):
                self.session.cookies.set(name, parsed[name], domain=".xueqiu.com", path="/")

    def replace_auth_cookie(self, cookie: str) -> None:
        self.session.cookies.clear()
        self._init_session()
        self._apply_auth_cookies(cookie)

    def _init_session(self):
        """先访问首页，让雪球下发新的风控 Cookie，再附上登录态。"""
        try:
            self.session.get(_BASE_URL, timeout=10)
        except Exception as e:
            logger.warning(f"session 初始化失败 ({e})，继续运行")

    def _refresh_waf(self) -> None:
        """acw_tc 大约 30 分钟过期。只换风控 Cookie，登录票用回 Secret 里的那份。"""
        for cookie in list(self.session.cookies):
            if cookie.name in _WAF_COOKIE_NAMES:
                self.session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        self._init_session()
        self._apply_auth_cookies(self.login_cookie)

    def _get(self, url: str, params: dict = None, *, retried: bool = False) -> Optional[dict]:
        if not self.session.cookies.get("acw_tc"):
            self._refresh_waf()
        previous = self._auth_cookie_values()
        try:
            resp = self.session.get(url, params=params, timeout=15)
        except Exception as e:
            logger.error(f"请求异常: {url} -> {e}")
            return None
        self._restore_user_cookies(previous)
        if resp.status_code == 403 and not _explicit_login_failure(resp):
            if retried:
                logger.error(f"刷新风控 Cookie 后仍然 HTTP 403: {url}")
                return None
            logger.warning(f"HTTP 403，刷新风控 Cookie 后重试: {url}")
            self._refresh_waf()
            return self._get(url, params, retried=True)
        reason = _auth_failure_reason(resp)
        if reason:
            logger.error(f"HTTP {resp.status_code}: {url}")
            raise CookieExpired(reason)
        try:
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError:
            logger.error(f"HTTP {resp.status_code}: {url}")
        except Exception as e:
            logger.error(f"请求异常: {url} -> {e}")
        return None

    def get_current_positions(self) -> list[dict]:
        """
        获取组合当前持仓，返回统一格式：
        [{'symbol': 'SH600519', 'name': '贵州茅台', 'weight': 30.5, 'prev_weight': 25.0, 'price': 1680.0}, ...]
        """
        # 方案1：新版接口
        url1 = f"{_BASE_URL}/cubes/rebalancing/current.json"
        params1 = {"cube_symbol": self.portfolio_id}
        data = self._get(url1, params1)
        source = "current"
        self.last_fetch_ok = data is not None

        # 方案2：v5 备用接口
        if data is None:
            url2 = f"{_STOCK_BASE}/v5/cube/rebalancing/current.json"
            params2 = {"cube_symbol": self.portfolio_id, "count": 1, "page": 1}
            data = self._get(url2, params2)
            source = "v5"
            self.last_fetch_ok = data is not None

        if data is None:
            data = self._get(
                f"{_BASE_URL}/cubes/rebalancing/history.json",
                {"cube_symbol": self.portfolio_id, "count": 1, "page": 1}
            )
            source = "history"
            self.last_fetch_ok = data is not None

        positions = []
        try:
            if source in ("current", "v5"):
                last_rb = (
                    data.get("data", {}).get("last_rb")
                    or data.get("last_rb")
                    or {}
                )
                holdings = last_rb.get("holdings", [])
            elif source == "history":
                records = data.get("list", [])
                if records:
                    holdings = records[0].get("rebalancing_histories", [])
                else:
                    holdings = []
            else:
                holdings = []

            for item in holdings:
                weight = float(item.get("weight") or item.get("target_weight") or 0)
                if weight <= 0:
                    continue
                raw_code = str(item.get("stock_symbol") or item.get("symbol") or "").upper()
                positions.append({
                    "symbol":      raw_code,
                    "name":        item.get("stock_name") or item.get("name") or raw_code,
                    "weight":      weight,
                    "prev_weight": float(item.get("prev_weight") or 0),
                    "price":       float(item.get("price") or 0),
                })
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning(f"持仓解析失败({e})，返回空列表")
            return []

        logger.info(f"[{self.portfolio_id}] 当前持仓 {len(positions)} 只 ({source})")
        return positions

    def get_latest_rebalancing(self) -> Optional[dict]:
        """获取最新调仓记录"""
        data = self._get(
            f"{_BASE_URL}/cubes/rebalancing/history.json",
            {"cube_symbol": self.portfolio_id, "count": 1, "page": 1}
        )
        if data is None:
            return None
        records = data.get("list", [])
        return records[0] if records else None


# ══════════════════════════════════════════════════════════════════
#  💾  状态持久化
# ══════════════════════════════════════════════════════════════════
_STATE_FILE = os.environ.get(
    "STATE_FILE",
    os.path.join(os.path.dirname(__file__), "monitor_state.json"),
)


def _load_state() -> dict:
    if os.path.exists(_STATE_FILE):
        try:
            with open(_STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(state: dict):
    try:
        with open(_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存状态失败: {e}")


def _save_cube_state(state: dict, cube_id: str, positions: list, nav_info: dict, rb_id) -> None:
    """保存组合持仓快照和调仓记录ID"""
    state[cube_id] = {
        "positions": positions,
        "nav": nav_info,
        "last_rb_id": rb_id,
        "last_check": datetime.now().isoformat(),
    }


# ══════════════════════════════════════════════════════════════════
#  🔍  数据解析
# ══════════════════════════════════════════════════════════════════


def parse_nav_from_rebalancing(latest_rb: dict) -> dict[str, Any]:
    """从调仓记录中解析组合名称"""
    if not latest_rb:
        return {"name": ""}
    data = latest_rb if isinstance(latest_rb, dict) else {}
    histories = data.get("rebalancing_histories", [])
    cube_name = (
        histories[0].get("cube_name", "")
        if histories else data.get("cube_name", "")
    )
    return {"name": cube_name}


# ══════════════════════════════════════════════════════════════════
#  🔔  变动检测
# ══════════════════════════════════════════════════════════════════

def detect_changes(old: list[dict], new: list[dict]) -> list[dict]:
    """
    对比新旧持仓，以上次保存的 weight 为基准检测变动（而非 prev_weight）。
    这样可避免同一次调仓被多轮检查重复触发。

    返回变动列表，每项格式：
    {'type': '新增'/'卖出'/'加仓'/'减仓', 'symbol': ..., 'name': ...,
     'old_weight': ..., 'new_weight': ..., 'price': ...}
    """
    old_map = {p["symbol"]: p for p in old}
    new_map = {p["symbol"]: p for p in new}
    changes = []

    for sym, pos in new_map.items():
        curr_w = pos["weight"]
        if sym not in old_map:
            changes.append({
                "type": "新增",
                "symbol": sym,
                "name": pos["name"],
                "old_weight": 0,
                "new_weight": curr_w,
                "price": pos["price"],
            })
        else:
            # 使用上次保存的 weight（而非 API 的 prev_weight）进行对比，防止重复触发
            old_w = old_map[sym].get("weight", 0)
            delta = curr_w - old_w
            if abs(delta) >= WEIGHT_CHANGE_THRESHOLD:
                changes.append({
                    "type": "加仓" if delta > 0 else "减仓",
                    "symbol": sym,
                    "name": pos["name"],
                    "old_weight": old_w,
                    "new_weight": curr_w,
                    "price": pos["price"],
                })

    for sym, pos in old_map.items():
        if sym not in new_map:
            changes.append({
                "type": "卖出",
                "symbol": sym,
                "name": pos["name"],
                "old_weight": pos.get("weight", 0),
                "new_weight": 0,
                "price": pos["price"],
            })

    return changes


# ══════════════════════════════════════════════════════════════════
#  📨  通知内容构建
# ══════════════════════════════════════════════════════════════════

_TYPE_EMOJI = {"新增": "🟢", "加仓": "📈", "减仓": "📉", "卖出": "🔴"}


def build_markdown(cube_id: str, nav_info: dict, changes: list[dict]) -> tuple[str, str]:
    """
    构建钉钉 Markdown 消息。
    返回 (title, content)
    """
    name = nav_info.get("name") or cube_id
    now = datetime.now().strftime("%m/%d %H:%M")

    title = f"雪球组合变动 · {name}"

    lines = [
        f"## 📈 {name} 持仓变动",
        f"> 组合代码：**{cube_id}**　｜　检测时间：{now}",
        "",
        "### 📋 变动明细",
    ]

    for c in changes:
        emoji = _TYPE_EMOJI.get(c["type"], "•")
        change_type = c["type"]
        sym = c["symbol"]
        n = c["name"]
        old_w = c["old_weight"]
        new_w = c["new_weight"]
        price = c["price"]

        if change_type == "新增":
            detail = f"建仓 **{new_w:.1f}%**"
        elif change_type == "卖出":
            detail = f"清仓（原仓位 {old_w:.1f}%）"
        elif change_type == "加仓":
            detail = f"{old_w:.1f}% → **{new_w:.1f}%**（+{new_w - old_w:.1f}%）"
        else:
            detail = f"{old_w:.1f}% → **{new_w:.1f}%**（{new_w - old_w:.1f}%）"

        price_str = f"  当前价 ¥{price:.2f}" if price else ""
        lines.append(f"- {emoji} **{change_type}** {n}（{sym}）：{detail}{price_str}")

    content = "\n".join(lines)
    return title, content


# ══════════════════════════════════════════════════════════════════
#  🔄  单次监控执行
# ══════════════════════════════════════════════════════════════════

def _explicit_login_failure(resp: requests.Response) -> bool:
    try:
        data = resp.json()
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    description = str(data.get("error_description") or "")
    code = str(data.get("error_code") or "")
    return code in {"10022", "400016"} or any(word in description for word in ("登录", "cookie", "Cookie"))


def _auth_failure_reason(resp: requests.Response) -> Optional[str]:
    """401，或响应明确要求登录。单纯的 HTTP 403 是风控页，不是登录票失效。"""
    if resp.status_code == 401:
        return "HTTP 401"
    if _explicit_login_failure(resp):
        try:
            data = resp.json()
        except Exception:
            return "需要登录"
        description = str(data.get("error_description") or "")
        code = str(data.get("error_code") or "")
        return description[:80] or f"error_code {code}" or "需要登录"
    return None


def monitor_once(client: XueQiuClient, notifier: Notifier) -> bool:
    """检查一轮。返回 True 表示 Cookie 已失效，调用方应退出。"""
    state = _load_state()
    state_changed = False
    client.relogin_tried = False

    if _check_token_expiry(state, notifier):
        state_changed = True

    for cube_id in MONITORED_CUBES:
        logger.info(f"─── 检查组合 {cube_id} ───")
        while True:
            try:
                client.portfolio_id = cube_id
                new_positions = client.get_current_positions()
                logger.info(f"持仓数量: {len(new_positions)} 只")

                if not client.last_fetch_ok:
                    logger.error(f"[{cube_id}] 没有拿到持仓数据，保留旧快照")
                    break

                if not new_positions:
                    logger.warning(f"[{cube_id}] 持仓列表为空，可能组合不存在或没有公开持仓")

                latest_rb = client.get_latest_rebalancing()
                nav_info = parse_nav_from_rebalancing(latest_rb)
                if not nav_info.get("name"):
                    nav_info["name"] = cube_id
                logger.info(f"组合名称: {nav_info['name']}")

                rb_id = latest_rb.get("id") if latest_rb else None
                last_rb_id = state.get(cube_id, {}).get("last_rb_id")

                if rb_id and rb_id == last_rb_id:
                    logger.info(f"[{cube_id}] 调仓记录未变化（ID={rb_id}），跳过通知")
                    if cube_id in state:
                        state[cube_id]["last_check"] = datetime.now().isoformat()
                        state_changed = True
                    break

                if rb_id:
                    logger.info(f"[{cube_id}] 发现新调仓记录（ID={rb_id}，上次={last_rb_id}）")

                old_positions = state.get(cube_id, {}).get("positions", [])
                changes = detect_changes(old_positions, new_positions)

                if changes:
                    logger.info(f"[{cube_id}] 检测到 {len(changes)} 项变动，准备发送通知")
                    title, content = build_markdown(cube_id, nav_info, changes)
                    ok = notifier.send_markdown(title, content, cube_id=cube_id)
                    if ok:
                        logger.info(f"[{cube_id}] 通知发送成功")
                        _save_cube_state(state, cube_id, new_positions, nav_info, rb_id)
                        state_changed = True
                    else:
                        logger.error(f"[{cube_id}] 通知发送失败，保留旧状态，下次重试")
                else:
                    logger.info(f"[{cube_id}] 无持仓变动（阈值 {WEIGHT_CHANGE_THRESHOLD}%）")
                    _save_cube_state(state, cube_id, new_positions, nav_info, rb_id)
                    state_changed = True

            except CookieExpired as exc:
                if _fail_cookie(state, notifier, client, str(exc)):
                    continue
                return False
            except Exception as e:
                logger.error(f"[{cube_id}] 异常: {e}")
                logger.debug(traceback.format_exc())
                notifier.send_text(f"⚠️ 雪球监控异常\n组合：{cube_id}\n错误：{e}")

            time.sleep(2)
            break

    if state_changed:
        _save_state(state)
    return False


# ══════════════════════════════════════════════════════════════════
#  ✅  启动自检
# ══════════════════════════════════════════════════════════════════

def _check_config() -> bool:
    """检查配置完整性，有问题直接打印并返回 False"""
    ok = True
    if "你的token" in XUEQIU_COOKIE or not XUEQIU_COOKIE:
        print("❌ 未配置雪球 Cookie！请运行：uv run python login.py")
        ok = False
    if not MONITORED_CUBES or MONITORED_CUBES == ["ZH123456"]:
        print("❌ 未配置监控组合！请在 .env 文件或脚本顶部填写 MONITORED_CUBES")
        ok = False
    return ok


# ══════════════════════════════════════════════════════════════════
#  ▶  主程序（内置定时循环）
# ══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  雪球组合变动监控 v2.1")
    print("=" * 60)

    config_ok = _check_config()
    notifier, notify_errors = build_notifier()
    for err in notify_errors:
        print(f"❌ {err}")
    if not config_ok or notify_errors:
        print("\n💡 配置方式（推荐使用 .env 文件）：")
        print("   在脚本同目录创建 .env 文件，内容：")
        print("     XUEQIU_COOKIE=xq_a_token=xxx;u=xxx")
        print("     MONITORED_CUBES=ZH123456,ZH654321")
        print("     DINGTALK_ENABLED=true")
        print("     DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx")
        print("     TELEGRAM_ENABLED=true")
        print("     TELEGRAM_BOT_TOKEN=123456:abc")
        print("     TELEGRAM_CHAT_ID=123456789")
        print("     FEISHU_ENABLED=true")
        print("     FEISHU_APP_ID=cli_xxx")
        print("     FEISHU_APP_SECRET=xxx")
        print("     FEISHU_MODE=websocket")
        print("     FEISHU_RECEIVE_ID=oc_xxx")
        print("     CHECK_INTERVAL=300")
        sys.exit(1)

    print(f"\n📌 监控组合: {', '.join(MONITORED_CUBES)}")
    print(f"⏱  检查间隔: {CHECK_INTERVAL} 秒")
    print(f"📊 仓位变动阈值: ≥ {WEIGHT_CHANGE_THRESHOLD}%")
    print(f"📤 通知渠道: {notifier.describe()}")
    print(f"📅 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 初始化客户端（cookie 全局复用，portfolio_id 每次切换）
    client = XueQiuClient(XUEQIU_COOKIE, MONITORED_CUBES[0])

    logger.info("首次检查...")
    if monitor_once(client, notifier):
        sys.exit(2)

    try:
        while True:
            next_run = datetime.now().strftime("%H:%M:%S")
            logger.info(f"等待 {CHECK_INTERVAL} 秒后再次检查（下次约 {next_run}）...")
            time.sleep(CHECK_INTERVAL)
            if monitor_once(client, notifier):
                sys.exit(2)
    except KeyboardInterrupt:
        logger.info("监控已手动停止")
        print("\n👋 监控已停止")


if __name__ == "__main__":
    main()
