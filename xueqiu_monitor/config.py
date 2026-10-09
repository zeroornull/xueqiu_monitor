"""环境变量与路径。数值在导入时读取，调用处通过本模块属性访问。"""

import logging
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        load_dotenv(env_path)


_load_dotenv()

XUEQIU_COOKIE: str = os.environ.get(
    "XUEQIU_COOKIE",
    "xq_a_token=你的token;u=你的uid",
)

_cubes_env = os.environ.get("MONITORED_CUBES", "")
MONITORED_CUBES: list[str] = (
    [c.strip() for c in _cubes_env.split(",") if c.strip()]
    if _cubes_env
    else ["ZH123456"]
)

CHECK_INTERVAL: int = int(os.environ.get("CHECK_INTERVAL", "300"))
# 工作日盘中用 CHECK_INTERVAL；休市和周末用更长间隔，收盘前可缩短。
TRADING_HOURS_ONLY: bool = os.environ.get("TRADING_HOURS_ONLY", "true").lower() == "true"
OFF_HOURS_INTERVAL: int = int(os.environ.get("OFF_HOURS_INTERVAL", "1800"))
PRE_CLOSE_MINUTES: int = int(os.environ.get("PRE_CLOSE_MINUTES", "15"))
PRE_CLOSE_INTERVAL: int = int(os.environ.get("PRE_CLOSE_INTERVAL", "60"))
MARKET_CLOSE: str = os.environ.get("MARKET_CLOSE", "15:00")
WEIGHT_CHANGE_THRESHOLD: float = float(os.environ.get("WEIGHT_CHANGE_THRESHOLD", "0"))
LOG_FILE: str = os.environ.get("LOG_FILE", "xueqiu_monitor.log")

_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
if LOG_FILE:
    _handlers.append(logging.FileHandler(LOG_FILE, encoding="utf-8"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=_handlers,
)
