#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
雪球组合变动监控 - 钉钉通知脚本 v2.0
──────────────────────────────────────
功能：
  · 定时拉取雪球组合持仓数据
  · 检测持仓新增/卖出/加减仓（按仓位权重对比）
  · 有变动时通过钉钉机器人发送 Markdown 通知

依赖安装：
    pip install requests schedule python-dotenv

Token 获取方式：
  1. 浏览器登录 https://xueqiu.com
  2. F12 → Network → 任意请求 → Request Headers → Cookie
  3. 复制完整 Cookie 字符串，填入 .env 文件
"""

import json
import os
import sys
import time
import logging
import traceback
from datetime import datetime
from typing import Optional

import requests

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

# 钉钉机器人 Webhook（必填）
DINGTALK_WEBHOOK: str = os.environ.get(
    "DINGTALK_WEBHOOK",
    "https://oapi.dingtalk.com/robot/send?access_token=你的access_token"
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

# 是否 @所有人
AT_ALL: bool = os.environ.get("AT_ALL", "false").lower() == "true"

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
#  🌐  雪球 API 客户端（纯 requests，无第三方包依赖）
# ══════════════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════════════
#  🌐  雪球 API 客户端（参考用户提供的有效接口）
# ══════════════════════════════════════════════════════════════════
_BASE_URL   = "https://xueqiu.com"
_STOCK_BASE = "https://stock.xueqiu.com"


def _alert_cookie_expired():
    """Cookie 失效时输出高优先级日志"""
    logger.critical("雪球 Cookie 已失效，请更新 XUEQIU_COOKIE！")


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
            "Cookie": cookie,
        })
        self._init_session()

    def _init_session(self):
        try:
            self.session.get(_BASE_URL, timeout=10)
        except Exception as e:
            logger.warning(f"session 初始化失败 ({e})，继续运行")

    def _get(self, url: str, params: dict = None) -> Optional[dict]:
        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            logger.error(f"HTTP {status}: {url}")
            if status in (401, 403):
                _alert_cookie_expired()
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

        # 方案2：v5 备用接口
        if data is None:
            url2 = f"{_STOCK_BASE}/v5/cube/rebalancing/current.json"
            params2 = {"cube_symbol": self.portfolio_id, "count": 1, "page": 1}
            data = self._get(url2, params2)
            source = "v5"

        if data is None:
            data = self._get(
                f"{_BASE_URL}/cubes/rebalancing/history.json",
                {"cube_symbol": self.portfolio_id, "count": 1, "page": 1}
            )
            source = "history"

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
        except Exception as e:
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
#  📤  钉钉通知
# ══════════════════════════════════════════════════════════════════
class DingTalkNotifier:
    """钉钉自定义机器人（无加签方式）"""

    def __init__(self, webhook: str):
        self.webhook = webhook
        self._last_send: dict[str, float] = {}  # cube_id -> timestamp
        self.cooldown = 60  # 同一组合 60 秒内不重复发送

    def _post(self, payload: dict) -> bool:
        try:
            resp = requests.post(
                self.webhook,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            result = resp.json()
            if result.get("errcode") == 0:
                return True
            logger.error(f"钉钉发送失败: {result}")
            return False
        except Exception as e:
            logger.error(f"钉钉请求异常: {e}")
            return False

    def send_markdown(self, title: str, content: str, cube_id: str = "") -> bool:
        now = time.time()
        if cube_id and now - self._last_send.get(cube_id, 0) < self.cooldown:
            logger.info(f"[{cube_id}] 冷却期内，跳过重复通知")
            return False
        payload = {
            "msgtype": "markdown",
            "markdown": {"title": title, "text": content},
            "at": {"isAtAll": AT_ALL},
        }
        ok = self._post(payload)
        if ok and cube_id:
            self._last_send[cube_id] = now
        return ok

    def send_text(self, content: str) -> bool:
        payload = {
            "msgtype": "text",
            "text": {"content": content},
            "at": {"isAtAll": AT_ALL},
        }
        return self._post(payload)


# ══════════════════════════════════════════════════════════════════
#  💾  状态持久化
# ══════════════════════════════════════════════════════════════════
_STATE_FILE = os.path.join(os.path.dirname(__file__), "monitor_state.json")


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


# ══════════════════════════════════════════════════════════════════
#  🔍  数据解析
# ══════════════════════════════════════════════════════════════════


def parse_nav_from_rebalancing(latest_rb: dict) -> dict:
    """从调仓记录中解析组合名称和基本信息"""
    if not latest_rb:
        return {"name": "", "today_gain_rate": 0, "total_gain_rate": 0}
    data = latest_rb if isinstance(latest_rb, dict) else {}
    # 从 rebalancing_histories 第一条取组合名
    histories = data.get("rebalancing_histories", [])
    cube_name = (
        histories[0].get("cube_name", "")
        if histories else data.get("cube_name", "")
    )
    return {
        "name": cube_name,
        "today_gain_rate": 0,    # 调仓记录不含当日涨跌，需另查净值接口
        "total_gain_rate": 0,    # 同上
    }


# ══════════════════════════════════════════════════════════════════
#  🔔  变动检测
# ══════════════════════════════════════════════════════════════════

def detect_changes(old: list[dict], new: list[dict]) -> list[dict]:
    """
    对比新旧持仓，按 prev_weight → weight 变动检测。
    返回变动列表，每项格式：
    {'type': '新增'/'卖出'/'加仓'/'减仓', 'symbol': ..., 'name': ...,
     'old_weight': ..., 'new_weight': ..., 'price': ...}
    """
    old_map = {p["symbol"]: p for p in old}
    new_map = {p["symbol"]: p for p in new}
    changes = []

    for sym, pos in new_map.items():
        prev_w = pos.get("prev_weight", 0)
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
            old_prev = old_map[sym].get("prev_weight", 0)
            delta = curr_w - old_prev
            if abs(delta) >= WEIGHT_CHANGE_THRESHOLD:
                changes.append({
                    "type": "加仓" if delta > 0 else "减仓",
                    "symbol": sym,
                    "name": pos["name"],
                    "old_weight": old_prev,
                    "new_weight": curr_w,
                    "price": pos["price"],
                })

    for sym, pos in old_map.items():
        if sym not in new_map:
            changes.append({
                "type": "卖出",
                "symbol": sym,
                "name": pos["name"],
                "old_weight": pos.get("prev_weight", 0),
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
    today_rate = nav_info.get("today_gain_rate", 0)
    total_rate = nav_info.get("total_gain_rate", 0)
    now = datetime.now().strftime("%m/%d %H:%M")

    rate_emoji = "📈" if today_rate >= 0 else "📉"
    title = f"雪球组合变动 · {name}"

    lines = [
        f"## {rate_emoji} {name} 持仓变动",
        f"> 组合代码：**{cube_id}**　｜　检测时间：{now}",
        f"> 今日涨跌：**{today_rate:+.2f}%**　累计收益：{total_rate:+.2f}%",
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

def monitor_once(client: XueQiuClient, notifier: DingTalkNotifier):
    """对所有监控组合执行一次检查"""
    state = _load_state()
    state_changed = False

    for cube_id in MONITORED_CUBES:
        logger.info(f"─── 检查组合 {cube_id} ───")
        try:
            # 获取当前持仓
            client.portfolio_id = cube_id  # 切换组合
            new_positions = client.get_current_positions()
            logger.info(f"持仓数量: {len(new_positions)} 只")

            if not new_positions:
                logger.warning(f"[{cube_id}] 持仓列表为空，可能 Cookie 失效或组合不存在")

            # 获取最新调仓记录（含组合名称）
            latest_rb = client.get_latest_rebalancing()
            nav_info = parse_nav_from_rebalancing(latest_rb)
            if not nav_info.get("name"):
                nav_info["name"] = cube_id
            logger.info(f"组合名称: {nav_info['name']}")

            # 对比变动
            old_positions = state.get(cube_id, {}).get("positions", [])
            changes = detect_changes(old_positions, new_positions)

            if changes:
                logger.info(f"[{cube_id}] 检测到 {len(changes)} 项变动，准备发送通知")
                title, content = build_markdown(cube_id, nav_info, changes)
                ok = notifier.send_markdown(title, content, cube_id=cube_id)
                if ok:
                    logger.info(f"[{cube_id}] 通知发送成功")
                else:
                    logger.error(f"[{cube_id}] 通知发送失败")
            else:
                logger.info(f"[{cube_id}] 无持仓变动（阈值 {WEIGHT_CHANGE_THRESHOLD}%）")

            # 更新状态
            state[cube_id] = {
                "positions": new_positions,
                "nav": nav_info,
                "last_check": datetime.now().isoformat(),
            }
            state_changed = True

        except Exception as e:
            logger.error(f"[{cube_id}] 异常: {e}")
            logger.debug(traceback.format_exc())
            # 发送错误通知（避免静默失败）
            notifier.send_text(f"⚠️ 雪球监控异常\n组合：{cube_id}\n错误：{e}")

        time.sleep(2)  # 避免请求过快

    if state_changed:
        _save_state(state)


# ══════════════════════════════════════════════════════════════════
#  ✅  启动自检
# ══════════════════════════════════════════════════════════════════

def _check_config() -> bool:
    """检查配置完整性，有问题直接打印并返回 False"""
    ok = True
    if "你的token" in XUEQIU_COOKIE or not XUEQIU_COOKIE:
        print("❌ 未配置雪球 Cookie！请在 .env 文件或脚本顶部填写 XUEQIU_COOKIE")
        ok = False
    if "你的access_token" in DINGTALK_WEBHOOK or not DINGTALK_WEBHOOK:
        print("❌ 未配置钉钉 Webhook！请在 .env 文件或脚本顶部填写 DINGTALK_WEBHOOK")
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
    print("  雪球组合变动监控 v2.0  ·  钉钉通知")
    print("=" * 60)

    if not _check_config():
        print("\n💡 配置方式（推荐使用 .env 文件）：")
        print("   在脚本同目录创建 .env 文件，内容：")
        print("     XUEQIU_COOKIE=xq_a_token=xxx;u=xxx")
        print("     DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx")
        print("     MONITORED_CUBES=ZH123456,ZH654321")
        print("     CHECK_INTERVAL=300")
        sys.exit(1)

    print(f"\n📌 监控组合: {', '.join(MONITORED_CUBES)}")
    print(f"⏱  检查间隔: {CHECK_INTERVAL} 秒")
    print(f"📊 仓位变动阈值: ≥ {WEIGHT_CHANGE_THRESHOLD}%")
    print(f"📅 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    # 初始化客户端（cookie 全局复用，portfolio_id 每次切换）
    client = XueQiuClient(XUEQIU_COOKIE, MONITORED_CUBES[0])
    notifier = DingTalkNotifier(DINGTALK_WEBHOOK)

    # 启动时立即执行一次
    logger.info("首次检查...")
    monitor_once(client, notifier)

    # 定时循环
    try:
        while True:
            next_run = datetime.now().strftime("%H:%M:%S")
            logger.info(f"等待 {CHECK_INTERVAL} 秒后再次检查（下次约 {next_run}）...")
            time.sleep(CHECK_INTERVAL)
            monitor_once(client, notifier)
    except KeyboardInterrupt:
        logger.info("监控已手动停止")
        print("\n👋 监控已停止")


if __name__ == "__main__":
    main()
