"""雪球组合接口。三级降级，风控 Cookie 与登录票分开处理。"""

import atexit
import logging
from typing import Optional

import requests

from xueqiu_monitor.cookies import _is_user_id_token

logger = logging.getLogger(__name__)

_BASE_URL = "https://xueqiu.com"
_STOCK_BASE = "https://stock.xueqiu.com"
# 只带登录态。浏览器里的 acw_tc、ssxmod_itna 绑在原浏览器上，重放会得到 400/403。
_AUTH_COOKIE_NAMES = ("xq_a_token", "u", "xq_id_token", "xq_r_token", "xqat", "xq_is_login")
_WAF_COOKIE_NAMES = ("acw_tc", "acw_sc__v2", "ssxmod_itna", "ssxmod_itna2")


class CookieExpired(Exception):
    """当前 Cookie 已被雪球拒绝，或本地解析出的过期时间已到。"""


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
        url1 = f"{_BASE_URL}/cubes/rebalancing/current.json"
        params1 = {"cube_symbol": self.portfolio_id}
        data = self._get(url1, params1)
        source = "current"
        self.last_fetch_ok = data is not None

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

        if data is None:
            logger.warning(f"[{self.portfolio_id}] 持仓接口全部失败，返回空列表")
            return []

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
                    "symbol": raw_code,
                    "name": item.get("stock_name") or item.get("name") or raw_code,
                    "weight": weight,
                    "prev_weight": float(item.get("prev_weight") or 0),
                    "price": float(item.get("price") or 0),
                })
        except (KeyError, TypeError, AttributeError) as e:
            logger.warning(f"持仓解析失败({e})，返回空列表")
            return []

        logger.info(f"[{self.portfolio_id}] 当前持仓 {len(positions)} 只 ({source})")
        return positions

    def get_rebalancing_history(self, count: int = 20) -> Optional[list]:
        """获取最近的调仓记录，新的在前。请求失败返回 None。"""
        data = self._get(
            f"{_BASE_URL}/cubes/rebalancing/history.json",
            {"cube_symbol": self.portfolio_id, "count": count, "page": 1},
        )
        if data is None:
            return None
        records = data.get("list") or []
        return records if isinstance(records, list) else []

    def get_latest_rebalancing(self) -> Optional[dict]:
        """获取最新一条调仓记录"""
        records = self.get_rebalancing_history(count=1)
        if records is None:
            return None
        return records[0] if records else None
