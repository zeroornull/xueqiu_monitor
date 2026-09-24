"""Tests for position change detection logic."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from xueqiu_monitor import detect_changes


class TestDetectChanges:
    """Test suite for detect_changes() deduplication logic."""

    def test_new_position(self):
        """新增持仓应该被检测为'新增'"""
        old = []
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 0,
                "price": 1680.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "新增"
        assert changes[0]["symbol"] == "SH600519"
        assert changes[0]["old_weight"] == 0
        assert changes[0]["new_weight"] == 10.0

    def test_sold_position(self):
        """清仓应该被检测为'卖出'"""
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 8.0,
                "price": 1680.0,
            }
        ]
        new = []
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "卖出"
        assert changes[0]["symbol"] == "SH600519"
        assert changes[0]["old_weight"] == 10.0
        assert changes[0]["new_weight"] == 0

    def test_increase_above_threshold(self):
        """超过阈值的加仓应该被检测"""
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 8.0,
                "price": 1680.0,
            }
        ]
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 12.0,
                "prev_weight": 10.0,
                "price": 1700.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "加仓"
        assert changes[0]["old_weight"] == 10.0
        assert changes[0]["new_weight"] == 12.0

    def test_decrease_above_threshold(self):
        """超过阈值的减仓应该被检测"""
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 15.0,
                "prev_weight": 12.0,
                "price": 1680.0,
            }
        ]
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 13.0,
                "prev_weight": 15.0,
                "price": 1650.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "减仓"
        assert changes[0]["old_weight"] == 15.0
        assert changes[0]["new_weight"] == 13.0

    def test_change_below_threshold(self, monkeypatch):
        """低于阈值的变动应该被忽略"""
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 1.0)
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 9.5,
                "price": 1680.0,
            }
        ]
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.5,
                "prev_weight": 10.0,
                "price": 1690.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 0

    def test_change_exactly_at_threshold(self, monkeypatch):
        """恰好等于阈值的变动应该被检测"""
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 1.0)
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 9.0,
                "price": 1680.0,
            }
        ]
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 11.0,
                "prev_weight": 10.0,
                "price": 1690.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "加仓"

    def test_tiny_change_notifies_when_threshold_is_zero(self, monkeypatch):
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 0)
        old = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1.0}]
        new = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 10.2, "price": 1.0}]
        changes = detect_changes(old, new)
        assert len(changes) == 1
        assert changes[0]["type"] == "加仓"

    def test_no_change(self):
        """没有变动时应该返回空列表"""
        old = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 10.0,
                "price": 1680.0,
            }
        ]
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,
                "prev_weight": 10.0,
                "price": 1680.0,
            }
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 0

    def test_multiple_changes(self):
        """多个持仓同时变动应该全部检测到"""
        old = [
            {"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1680.0},
            {"symbol": "SH600036", "name": "招商银行", "weight": 15.0, "price": 35.0},
            {"symbol": "SZ000858", "name": "五粮液", "weight": 12.0, "price": 150.0},
        ]
        new = [
            {"symbol": "SH600519", "name": "贵州茅台", "weight": 13.0, "price": 1700.0},  # 加仓
            {"symbol": "SZ000858", "name": "五粮液", "weight": 10.0, "price": 145.0},  # 减仓
            {"symbol": "SZ002594", "name": "比亚迪", "weight": 8.0, "price": 250.0},  # 新增
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 4  # 加仓 + 减仓 + 新增 + 卖出

        types = {c["symbol"]: c["type"] for c in changes}
        assert types["SH600519"] == "加仓"
        assert types["SZ000858"] == "减仓"
        assert types["SZ002594"] == "新增"
        assert types["SH600036"] == "卖出"

    def test_uses_saved_weight_not_prev_weight(self):
        """
        关键测试：detect_changes 应该使用上次保存的 weight，
        而不是 API 返回的 prev_weight，以避免重复触发
        """
        # 上次保存的快照
        old = [
            {"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1680.0}
        ]
        # API 返回的新数据，prev_weight 可能和我们上次保存的不一致
        new = [
            {
                "symbol": "SH600519",
                "name": "贵州茅台",
                "weight": 10.0,  # weight 没变
                "prev_weight": 8.0,  # 但 prev_weight 显示之前是 8.0
                "price": 1680.0,
            }
        ]
        # 不应该检测到变动，因为 weight 10.0 -> 10.0
        changes = detect_changes(old, new)
        assert len(changes) == 0

    def test_empty_positions(self):
        """空持仓列表应该正常处理"""
        changes = detect_changes([], [])
        assert len(changes) == 0

    def test_price_update_no_weight_change(self):
        """价格变动但仓位不变时不应触发通知"""
        old = [
            {"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1680.0}
        ]
        new = [
            {"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1750.0}
        ]
        changes = detect_changes(old, new)
        assert len(changes) == 0
