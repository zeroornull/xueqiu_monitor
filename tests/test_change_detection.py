"""调仓记录里的主动操作才算变动，实时市值权重不算。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from xueqiu_monitor import changes_from_rebalancing


def _item(**kwargs):
    base = {
        "stock_symbol": "SH600519",
        "stock_name": "贵州茅台",
        "proactive": True,
        "price": 1680.0,
    }
    base.update(kwargs)
    return base


class TestChangesFromRebalancing:
    def test_new_position(self):
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight=None, prev_weight_adjusted=None, target_weight=1.0)]
        })
        assert len(changes) == 1
        assert changes[0]["type"] == "新增"
        assert changes[0]["old_weight"] == 0
        assert changes[0]["new_weight"] == 1.0

    def test_sold_position(self):
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight_adjusted=10.0, target_weight=0)]
        })
        assert changes[0]["type"] == "卖出"
        assert changes[0]["old_weight"] == 10.0
        assert changes[0]["new_weight"] == 0

    def test_increase_uses_adjusted_weight(self):
        """调仓前已经随行情漂过的仓位，才是这次操作的起点。"""
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(
                prev_weight=8.0,
                prev_weight_adjusted=10.0,
                target_weight=12.0,
            )]
        })
        assert changes[0]["type"] == "加仓"
        assert changes[0]["old_weight"] == 10.0
        assert changes[0]["new_weight"] == 12.0

    def test_decrease(self):
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight_adjusted=3.97, target_weight=3.0)]
        })
        assert changes[0]["type"] == "减仓"
        assert changes[0]["old_weight"] == 3.97
        assert changes[0]["new_weight"] == 3.0

    def test_below_threshold(self, monkeypatch):
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 1.0)
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight_adjusted=10.0, target_weight=10.5)]
        })
        assert changes == []

    def test_exactly_at_threshold(self, monkeypatch):
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 1.0)
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight_adjusted=10.0, target_weight=11.0)]
        })
        assert changes[0]["type"] == "加仓"

    def test_tiny_proactive_change_when_threshold_is_zero(self, monkeypatch):
        monkeypatch.setattr("xueqiu_monitor.WEIGHT_CHANGE_THRESHOLD", 0)
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(prev_weight_adjusted=2.94, target_weight=2.97)]
        })
        assert changes[0]["type"] == "加仓"
        assert round(changes[0]["new_weight"] - changes[0]["old_weight"], 2) == 0.03

    def test_passive_item_is_ignored(self):
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(
                proactive=False,
                prev_weight_adjusted=2.0,
                target_weight=2.06,
            )]
        })
        assert changes == []

    def test_target_matches_adjusted_weight(self):
        """目标仓位等于调仓前市值仓位，说明没有买卖。"""
        changes = changes_from_rebalancing({
            "rebalancing_histories": [_item(
                prev_weight=8.0,
                prev_weight_adjusted=10.0,
                target_weight=10.0,
            )]
        })
        assert changes == []

    def test_multiple_active_changes(self):
        changes = changes_from_rebalancing({
            "rebalancing_histories": [
                _item(stock_symbol="SH600585", stock_name="海螺水泥", prev_weight_adjusted=2.66, target_weight=3.0),
                _item(stock_symbol="SH600970", stock_name="中材国际", prev_weight_adjusted=3.97, target_weight=3.0),
                _item(stock_symbol="SZ002233", stock_name="塔牌集团", prev_weight=None, prev_weight_adjusted=None, target_weight=1.0),
                _item(stock_symbol="SH513120", stock_name="港股创新药ETF广发", proactive=False, prev_weight_adjusted=2.0, target_weight=2.06),
            ]
        })
        types = {item["symbol"]: item["type"] for item in changes}
        assert types == {
            "SH600585": "加仓",
            "SH600970": "减仓",
            "SZ002233": "新增",
        }

    def test_empty_record(self):
        assert changes_from_rebalancing(None) == []
        assert changes_from_rebalancing({}) == []
        assert changes_from_rebalancing({"rebalancing_histories": []}) == []
