"""按交易时段决定下一轮等待多久。休市拉长间隔，收盘前缩短。"""

from datetime import datetime
from typing import Any, Optional

from xueqiu_monitor import config


def _parse_hhmm(value: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        hour, minute = value.strip().split(":")
        return int(hour), int(minute)
    except ValueError:
        return default


def get_schedule_info(now: Optional[datetime] = None) -> dict[str, Any]:
    """
    返回当前调度状态：in_trading / phase / interval / label。

    交易时段默认：工作日 09:15-11:35、12:55-MARKET_CLOSE（默认 15:00）。
    收盘前 PRE_CLOSE_MINUTES 分钟使用更短间隔。结束后再留 5 分钟缓冲。
    """
    now = now or datetime.now()
    base_interval = max(10, int(config.CHECK_INTERVAL or 300))
    off_interval = max(base_interval, int(config.OFF_HOURS_INTERVAL or 1800))
    pre_close_interval = max(10, int(config.PRE_CLOSE_INTERVAL or 60))
    pre_close_minutes = max(0, int(config.PRE_CLOSE_MINUTES or 0))
    close_h, close_m = _parse_hhmm(config.MARKET_CLOSE, (15, 0))
    market_close = f"{close_h:02d}:{close_m:02d}"

    if not config.TRADING_HOURS_ONLY:
        return {
            "in_trading": True,
            "phase": "always",
            "interval": base_interval,
            "label": "全天候",
            "market_close": market_close,
        }

    if now.weekday() >= 5:
        return {
            "in_trading": False,
            "phase": "weekend",
            "interval": off_interval,
            "label": "周末休市",
            "market_close": market_close,
        }

    minutes = now.hour * 60 + now.minute
    morning = (9 * 60 + 15, 11 * 60 + 35)
    afternoon_start = 12 * 60 + 55
    close_min = close_h * 60 + close_m
    afternoon_end = close_min + 5
    pre_close_start = max(afternoon_start, close_min - pre_close_minutes)

    if morning[0] <= minutes <= morning[1]:
        return {
            "in_trading": True,
            "phase": "morning",
            "interval": base_interval,
            "label": "上午盘",
            "market_close": market_close,
        }
    if afternoon_start <= minutes <= afternoon_end:
        if pre_close_minutes and minutes >= pre_close_start:
            return {
                "in_trading": True,
                "phase": "pre_close",
                "interval": min(base_interval, pre_close_interval),
                "label": "收盘前加速",
                "market_close": market_close,
            }
        return {
            "in_trading": True,
            "phase": "afternoon",
            "interval": base_interval,
            "label": "下午盘",
            "market_close": market_close,
        }

    return {
        "in_trading": False,
        "phase": "off",
        "interval": off_interval,
        "label": "非交易时段",
        "market_close": market_close,
    }


def next_check_interval(now: Optional[datetime] = None) -> int:
    return int(get_schedule_info(now)["interval"])
