"""monitor_state.json 读写。"""

import json
import logging
import os
from datetime import datetime

from xueqiu_monitor.config import PROJECT_ROOT

logger = logging.getLogger(__name__)

_STATE_FILE = os.environ.get("STATE_FILE", str(PROJECT_ROOT / "monitor_state.json"))


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
