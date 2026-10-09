"""从调仓记录提取主动买卖。不比较实时市值权重。"""

from datetime import datetime
from typing import Any, Optional

from xueqiu_monitor import config


def _optional_float(value) -> Optional[float]:
    if value is None or value == "":
        return None
    return float(value)


def changes_from_rebalancing(record: Optional[dict]) -> list[dict]:
    """
    从一条调仓记录提取主动操作。

    行情漂移不在 rebalancing_histories 里，或 proactive 为 false。
    比较的是调仓前实际仓位 prev_weight_adjusted 和目标仓位 target_weight。
    """
    if not record:
        return []
    changes = []
    for item in record.get("rebalancing_histories") or []:
        if not isinstance(item, dict) or item.get("proactive") is False:
            continue
        symbol = str(item.get("stock_symbol") or item.get("symbol") or "").upper()
        if not symbol:
            continue
        name = item.get("stock_name") or item.get("name") or symbol
        target = _optional_float(item.get("target_weight"))
        if target is None:
            target = _optional_float(item.get("weight"))
        if target is None:
            continue
        baseline = _optional_float(item.get("prev_weight_adjusted"))
        if baseline is None:
            baseline = _optional_float(item.get("prev_weight"))
        if baseline is None:
            baseline = 0.0
        price = _optional_float(item.get("price")) or 0.0
        if target <= 0 and baseline > 0:
            change_type = "卖出"
            new_weight = 0.0
        elif baseline <= 0 < target:
            change_type = "新增"
            new_weight = target
        else:
            delta = target - baseline
            if delta == 0 or abs(delta) < config.WEIGHT_CHANGE_THRESHOLD:
                continue
            change_type = "加仓" if delta > 0 else "减仓"
            new_weight = target
        changes.append({
            "type": change_type,
            "symbol": symbol,
            "name": name,
            "old_weight": baseline,
            "new_weight": new_weight,
            "price": price,
        })
    return changes


def parse_nav_from_rebalancing(latest_rb: dict) -> dict[str, Any]:
    """从调仓记录中解析组合名称、调仓时间和类型"""
    if not latest_rb:
        return {"name": ""}
    data = latest_rb if isinstance(latest_rb, dict) else {}
    histories = data.get("rebalancing_histories") or []
    cube_name = ""
    if histories and isinstance(histories[0], dict):
        cube_name = histories[0].get("cube_name") or ""
    if not cube_name:
        cube_name = data.get("cube_name") or ""
    info: dict[str, Any] = {"name": cube_name}
    created = data.get("created_at")
    if isinstance(created, (int, float)) and created > 0:
        info["rebalanced_at"] = datetime.fromtimestamp(created / 1000).strftime("%m/%d %H:%M")
    if data.get("category") == "sys_rebalancing":
        info["rb_kind"] = "系统调仓"
    elif data.get("category") == "user_rebalancing":
        info["rb_kind"] = "调仓"
    return info
