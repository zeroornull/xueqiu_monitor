"""持仓变动通知正文。渠道只负责把这段文字送出去。"""

from datetime import datetime

_TYPE_EMOJI = {"新增": "🟢", "加仓": "📈", "减仓": "📉", "卖出": "🔴"}


def _format_weight(value: float) -> str:
    """一位小数能看清时用一位，否则保留两位，避免 0.03 显示成 0.0。"""
    text = f"{value:.2f}"
    if text.endswith("0"):
        text = text[:-1]
    return text


def _format_delta(value: float) -> str:
    sign = "+" if value > 0 else ""
    return f"{sign}{_format_weight(value)}"


def build_markdown(cube_id: str, nav_info: dict, changes: list[dict]) -> tuple[str, str]:
    """
    构建钉钉 Markdown 消息。
    返回 (title, content)
    """
    name = nav_info.get("name") or cube_id
    now = datetime.now().strftime("%m/%d %H:%M")

    title = f"雪球组合变动 · {name}"

    extra = ""
    if nav_info.get("rb_kind"):
        extra += f"　｜　{nav_info['rb_kind']}"
    if nav_info.get("rebalanced_at"):
        extra += f"　｜　调仓时间：{nav_info['rebalanced_at']}"
    lines = [
        f"## 📈 {name} 持仓变动",
        f"> 组合代码：**{cube_id}**　｜　检测时间：{now}{extra}",
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
            detail = f"建仓 **{_format_weight(new_w)}%**"
        elif change_type == "卖出":
            detail = f"清仓（原仓位 {_format_weight(old_w)}%）"
        elif change_type == "加仓":
            detail = f"{_format_weight(old_w)}% → **{_format_weight(new_w)}%**（{_format_delta(new_w - old_w)}%）"
        else:
            detail = f"{_format_weight(old_w)}% → **{_format_weight(new_w)}%**（{_format_delta(new_w - old_w)}%）"

        price_str = f"  当前价 ¥{price:.2f}" if price else ""
        lines.append(f"- {emoji} **{change_type}** {n}（{sym}）：{detail}{price_str}")

    content = "\n".join(lines)
    return title, content
