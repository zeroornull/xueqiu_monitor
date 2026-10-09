"""交易时段调度。不请求雪球。"""

from datetime import datetime

import xueqiu_monitor.config as config
from xueqiu_monitor.schedule import get_schedule_info, next_check_interval


def _use_defaults(monkeypatch):
    monkeypatch.setattr(config, "TRADING_HOURS_ONLY", True)
    monkeypatch.setattr(config, "CHECK_INTERVAL", 300)
    monkeypatch.setattr(config, "OFF_HOURS_INTERVAL", 1800)
    monkeypatch.setattr(config, "PRE_CLOSE_MINUTES", 15)
    monkeypatch.setattr(config, "PRE_CLOSE_INTERVAL", 60)
    monkeypatch.setattr(config, "MARKET_CLOSE", "15:00")


def test_morning_session_uses_check_interval(monkeypatch):
    _use_defaults(monkeypatch)
    info = get_schedule_info(datetime(2026, 10, 5, 10, 0))
    assert info["phase"] == "morning"
    assert info["in_trading"] is True
    assert info["interval"] == 300
    assert next_check_interval(datetime(2026, 10, 5, 10, 0)) == 300


def test_afternoon_before_pre_close(monkeypatch):
    _use_defaults(monkeypatch)
    info = get_schedule_info(datetime(2026, 10, 5, 13, 30))
    assert info["phase"] == "afternoon"
    assert info["interval"] == 300


def test_pre_close_uses_shorter_interval(monkeypatch):
    _use_defaults(monkeypatch)
    info = get_schedule_info(datetime(2026, 10, 5, 14, 50))
    assert info["phase"] == "pre_close"
    assert info["label"] == "收盘前加速"
    assert info["interval"] == 60


def test_close_buffer_still_counts_as_session(monkeypatch):
    _use_defaults(monkeypatch)
    info = get_schedule_info(datetime(2026, 10, 5, 15, 5))
    assert info["phase"] == "pre_close"
    assert get_schedule_info(datetime(2026, 10, 5, 15, 6))["phase"] == "off"


def test_off_hours_and_weekend(monkeypatch):
    _use_defaults(monkeypatch)
    assert get_schedule_info(datetime(2026, 10, 5, 8, 0))["phase"] == "off"
    weekend = get_schedule_info(datetime(2026, 10, 10, 10, 0))
    assert weekend["phase"] == "weekend"
    assert weekend["interval"] == 1800


def test_always_on_ignores_calendar(monkeypatch):
    _use_defaults(monkeypatch)
    monkeypatch.setattr(config, "TRADING_HOURS_ONLY", False)
    info = get_schedule_info(datetime(2026, 10, 10, 3, 0))
    assert info["phase"] == "always"
    assert info["interval"] == 300


def test_bad_market_close_falls_back_to_1500(monkeypatch):
    _use_defaults(monkeypatch)
    monkeypatch.setattr(config, "MARKET_CLOSE", "not-a-time")
    info = get_schedule_info(datetime(2026, 10, 5, 14, 50))
    assert info["market_close"] == "15:00"
    assert info["phase"] == "pre_close"
