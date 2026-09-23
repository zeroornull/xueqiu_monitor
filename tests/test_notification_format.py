"""Tests for notification formatting."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from xueqiu_monitor import build_markdown
from notifier import _markdown_to_html, _markdown_to_feishu


class TestBuildMarkdown:
    """Test suite for build_markdown() notification formatting."""

    def test_single_new_position(self):
        """单个新增持仓的通知格式"""
        changes = [
            {
                "type": "新增",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "old_weight": 0,
                "new_weight": 10.0,
                "price": 1680.0,
            }
        ]
        nav_info = {"name": "价值投资组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "价值投资组合" in title
        assert "ZH123456" in content
        assert "🟢" in content  # 新增 emoji
        assert "贵州茅台" in content
        assert "SH600519" in content
        assert "建仓" in content
        assert "10.0%" in content
        assert "¥1680.00" in content

    def test_sold_position(self):
        """清仓持仓的通知格式"""
        changes = [
            {
                "type": "卖出",
                "symbol": "SH600036",
                "name": "招商银行",
                "old_weight": 15.0,
                "new_weight": 0,
                "price": 35.0,
            }
        ]
        nav_info = {"name": "测试组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "🔴" in content  # 卖出 emoji
        assert "招商银行" in content
        assert "清仓" in content
        assert "15.0%" in content

    def test_increase_position(self):
        """加仓的通知格式"""
        changes = [
            {
                "type": "加仓",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "old_weight": 10.0,
                "new_weight": 13.5,
                "price": 1700.0,
            }
        ]
        nav_info = {"name": "测试组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "📈" in content  # 加仓 emoji
        assert "10.0%" in content
        assert "13.5%" in content
        assert "+3.5%" in content

    def test_decrease_position(self):
        """减仓的通知格式"""
        changes = [
            {
                "type": "减仓",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "old_weight": 15.0,
                "new_weight": 12.0,
                "price": 1680.0,
            }
        ]
        nav_info = {"name": "测试组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "📉" in content  # 减仓 emoji
        assert "15.0%" in content
        assert "12.0%" in content
        assert "-3.0%" in content

    def test_multiple_changes(self):
        """多个变动的通知格式"""
        changes = [
            {
                "type": "新增",
                "symbol": "SZ002594",
                "name": "比亚迪",
                "old_weight": 0,
                "new_weight": 8.0,
                "price": 250.0,
            },
            {
                "type": "卖出",
                "symbol": "SH600036",
                "name": "招商银行",
                "old_weight": 15.0,
                "new_weight": 0,
                "price": 35.0,
            },
        ]
        nav_info = {"name": "测试组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "比亚迪" in content
        assert "招商银行" in content
        assert content.count("- ") == 2  # 两项变动

    def test_missing_nav_name(self):
        """nav_info 缺少 name 时应该使用 cube_id"""
        changes = [
            {
                "type": "新增",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "old_weight": 0,
                "new_weight": 10.0,
                "price": 1680.0,
            }
        ]
        nav_info = {}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "ZH123456" in title
        assert "ZH123456" in content

    def test_zero_price(self):
        """价格为 0 时不应显示价格信息"""
        changes = [
            {
                "type": "新增",
                "symbol": "SH600519",
                "name": "贵州茅台",
                "old_weight": 0,
                "new_weight": 10.0,
                "price": 0,
            }
        ]
        nav_info = {"name": "测试组合"}
        title, content = build_markdown("ZH123456", nav_info, changes)

        assert "当前价" not in content
        assert "¥" not in content


class TestMarkdownConversion:
    """Test suite for Markdown to HTML/Feishu conversion."""

    def test_markdown_to_html_basic(self):
        """基本 Markdown 转 HTML"""
        markdown = "## 标题\n**粗体** 普通文本"
        html = _markdown_to_html(markdown)

        assert "<b>标题</b>" in html
        assert "<b>粗体</b>" in html
        assert "普通文本" in html

    def test_markdown_to_html_quote(self):
        """引用块转换"""
        markdown = "> 这是引用\n普通文本"
        html = _markdown_to_html(markdown)

        assert "这是引用" in html
        assert ">" not in html  # 引用符号应该被移除

    def test_markdown_to_html_heading_levels(self):
        """不同级别的标题"""
        markdown = "## 二级标题\n### 三级标题"
        html = _markdown_to_html(markdown)

        assert "<b>二级标题</b>" in html
        assert "<b>三级标题</b>" in html

    def test_markdown_to_html_escaping(self):
        """特殊字符应该被转义"""
        markdown = "价格 < 100 && 价格 > 50"
        html = _markdown_to_html(markdown)

        assert "&lt;" in html
        assert "&gt;" in html
        assert "&amp;" in html

    def test_markdown_to_html_truncation(self):
        """超长文本应该被截断"""
        markdown = "A" * 5000
        html = _markdown_to_html(markdown)

        assert len(html) <= 4100  # 4000 + "\n…"
        assert html.endswith("…")

    def test_markdown_to_feishu_basic(self):
        """Feishu Markdown 转换"""
        markdown = "## 标题\n**粗体** 普通文本"
        feishu = _markdown_to_feishu(markdown)

        assert "**标题**" in feishu
        assert "**粗体**" in feishu
        assert "普通文本" in feishu

    def test_markdown_to_feishu_quote_removal(self):
        """Feishu 格式移除引用符号"""
        markdown = "> 这是引用"
        feishu = _markdown_to_feishu(markdown)

        assert "这是引用" in feishu
        assert ">" not in feishu

    def test_markdown_to_feishu_truncation(self):
        """Feishu 超长文本截断"""
        markdown = "B" * 5000
        feishu = _markdown_to_feishu(markdown)

        assert len(feishu) <= 4100
        assert feishu.endswith("…")
