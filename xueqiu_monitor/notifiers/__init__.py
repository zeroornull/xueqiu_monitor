"""已启用的通知渠道。一次调用发到每一个，失败的渠道不挡住其余渠道。"""

from xueqiu_monitor.notifiers.bark import from_env as bark_from_env
from xueqiu_monitor.notifiers.base import Notifier, _in_cooldown
from xueqiu_monitor.notifiers.dingtalk import from_env as dingtalk_from_env
from xueqiu_monitor.notifiers.discord import from_env as discord_from_env
from xueqiu_monitor.notifiers.feishu import from_env as feishu_from_env
from xueqiu_monitor.notifiers.feishu_webhook import from_env as feishu_webhook_from_env
from xueqiu_monitor.notifiers.gotify import from_env as gotify_from_env
from xueqiu_monitor.notifiers.http_webhook import from_env as http_webhook_from_env
from xueqiu_monitor.notifiers.matrix import from_env as matrix_from_env
from xueqiu_monitor.notifiers.ntfy import from_env as ntfy_from_env
from xueqiu_monitor.notifiers.pushdeer import from_env as pushdeer_from_env
from xueqiu_monitor.notifiers.pushplus import from_env as pushplus_from_env
from xueqiu_monitor.notifiers.pushover import from_env as pushover_from_env
from xueqiu_monitor.notifiers.serverchan import from_env as serverchan_from_env
from xueqiu_monitor.notifiers.slack import from_env as slack_from_env
from xueqiu_monitor.notifiers.smtp import from_env as smtp_from_env
from xueqiu_monitor.notifiers.teams import from_env as teams_from_env
from xueqiu_monitor.notifiers.telegram import from_env as telegram_from_env
from xueqiu_monitor.notifiers.wecom import from_env as wecom_from_env
from xueqiu_monitor.notifiers.wxpusher import from_env as wxpusher_from_env

_LOADERS = (
    dingtalk_from_env,
    telegram_from_env,
    feishu_from_env,
    feishu_webhook_from_env,
    wecom_from_env,
    slack_from_env,
    discord_from_env,
    smtp_from_env,
    http_webhook_from_env,
    ntfy_from_env,
    gotify_from_env,
    pushover_from_env,
    teams_from_env,
    matrix_from_env,
    serverchan_from_env,
    pushplus_from_env,
    bark_from_env,
    wxpusher_from_env,
    pushdeer_from_env,
)


def build_notifier() -> tuple[Notifier, list[str]]:
    """按启用开关组装通知器。启用了但缺凭证时记一条错误并跳过该渠道。"""
    channels = []
    errors: list[str] = []
    for load in _LOADERS:
        channel = load(errors)
        if channel is not None:
            channels.append(channel)
    return Notifier(channels), errors


__all__ = ["Notifier", "_in_cooldown", "build_notifier"]
