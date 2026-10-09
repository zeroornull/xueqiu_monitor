"""定时检查组合调仓，有主动变动时通知。"""

import logging
import sys
import time
import traceback
from datetime import datetime

from xueqiu_monitor import config
from xueqiu_monitor.changes import changes_from_rebalancing, parse_nav_from_rebalancing
from xueqiu_monitor.client import CookieExpired, XueQiuClient
from xueqiu_monitor.cookies import _get_token_expiry, _token_state
from xueqiu_monitor.messages import build_markdown
from xueqiu_monitor.notifiers import Notifier, build_notifier
from xueqiu_monitor.schedule import get_schedule_info
from xueqiu_monitor.state import _load_state, _save_cube_state, _save_state

logger = logging.getLogger(__name__)


def _cookie_renew_hint() -> str:
    return (
        "请重新登录后更新 Cookie：\n"
        "- 本机执行 `uv run python -m xueqiu_monitor.login`\n"
        "- k3s 更新 `.env` 后执行 `k3s/release.sh`"
    )


def _check_token_expiry(state: dict, notifier: Notifier) -> bool:
    """过期前 1 天提醒一次。返回 True 表示 state 已变更。"""
    token_state = _token_state(state)
    expiry = _get_token_expiry(config.XUEQIU_COOKIE)
    if expiry is None:
        return False

    token_state["expiry"] = expiry
    remaining_hours = (expiry - time.time()) / 3600
    if remaining_hours <= 0 or remaining_hours > 24 or token_state.get("notified_expiry"):
        return False

    logger.warning(f"雪球 Cookie 将在 {remaining_hours:.1f} 小时后过期")
    content = (
        f"## ⚠️ 雪球 Cookie 即将过期\n\n"
        f"> 过期时间：**{datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')}**\n"
        f"> 剩余：**{remaining_hours:.1f} 小时**\n\n"
        f"{_cookie_renew_hint()}"
    )
    if notifier.send_markdown("雪球 Cookie 即将过期", content):
        token_state["notified_expiry"] = True
    return True


def _install_cookie(client, header: str) -> None:
    from xueqiu_monitor.login import _ENV_PATH, upsert_env

    upsert_env(_ENV_PATH, "XUEQIU_COOKIE", header)
    config.XUEQIU_COOKIE = header
    client.replace_auth_cookie(header)


def _profile_cookie() -> str | None:
    try:
        from xueqiu_monitor.login import _PROFILE_DIR, profile_cookie_header
    except ImportError:
        return None
    return profile_cookie_header(_PROFILE_DIR)


def _adopt_profile_cookie(client) -> bool:
    """Chrome 配置里有更新的登录票时直接换上，不打开窗口。"""
    header = _profile_cookie()
    if not header or header == config.XUEQIU_COOKIE:
        return False
    new_expiry = _get_token_expiry(header) or 0
    old_expiry = _get_token_expiry(config.XUEQIU_COOKIE) or 0
    if old_expiry and new_expiry <= old_expiry:
        return False
    _install_cookie(client, header)
    logger.info("已从本机 Chrome 配置读取登录 Cookie")
    return True


def _attempt_relogin(client) -> str:
    """ok / sms / failed / unavailable。成功时写回 .env 并换上新 Cookie。"""
    if _adopt_profile_cookie(client):
        return "ok"
    try:
        from xueqiu_monitor.login import acquire_cookie
    except ImportError:
        logger.error("无法自动登录：当前环境没有登录模块")
        return "unavailable"
    try:
        import playwright  # noqa: F401
    except ImportError:
        logger.error("无法自动登录：当前环境没有 Playwright")
        return "unavailable"
    logger.warning("Chrome 配置里没有更新的登录态，尝试打开浏览器重新登录")
    result = acquire_cookie(interactive=False, current=config.XUEQIU_COOKIE)
    if result.status == "ok" and result.cookie and result.cookie != config.XUEQIU_COOKIE:
        _install_cookie(client, result.cookie)
        logger.info("重新登录成功，已更新 Cookie")
        return "ok"
    if result.status == "sms":
        logger.error("自动登录遇到短信验证，已放弃")
        return "sms"
    logger.error(f"自动重新登录未成功：{result.message or result.status}")
    return "failed" if result.status != "unavailable" else "unavailable"


def _fail_cookie(state: dict, notifier: Notifier, client, reason: str) -> bool:
    """本机若能换到更新的登录票就立刻重试。换不到也继续按间隔请求，不退出。"""
    if not client.relogin_tried:
        client.relogin_tried = True
        if _attempt_relogin(client) == "ok":
            return True
    _stop_for_cookie(state, notifier, reason)
    return False


def _stop_for_cookie(state: dict, notifier: Notifier, reason: str) -> None:
    """通知一次。进程继续按间隔请求，不把这份 Cookie 判死。"""
    token_state = _token_state(state)
    expiry = _get_token_expiry(config.XUEQIU_COOKIE)
    until = ""
    if expiry:
        until = f"\n> 登录票标注到期：**{datetime.fromtimestamp(expiry).strftime('%Y-%m-%d %H:%M')}**"
    logger.warning(f"雪球请求被拒绝，下一轮继续：{reason}")
    if token_state.get("auth_notified") and not token_state.get("notify_pending"):
        return
    content = (
        f"## ⚠️ 雪球请求被拒绝\n\n"
        f"> 原因：{reason}{until}\n\n"
        f"监控保持运行，按检查间隔继续请求。\n"
        f"这份登录票由雪球签发，有效期大约 30 天，到期前不用重新登录。\n"
    )
    sent = notifier.send_markdown("雪球请求被拒绝", content)
    token_state["auth_notified"] = bool(sent)
    token_state["notify_pending"] = not sent
    if not sent:
        logger.error("请求失败通知没发出去，下一轮再试一次")
    _save_state(state)


def monitor_once(client: XueQiuClient, notifier: Notifier) -> bool:
    """检查一轮。返回 True 表示 Cookie 已失效，调用方应退出。"""
    state = _load_state()
    state_changed = False
    client.relogin_tried = False

    if _check_token_expiry(state, notifier):
        state_changed = True

    for cube_id in config.MONITORED_CUBES:
        logger.info(f"─── 检查组合 {cube_id} ───")
        while True:
            try:
                client.portfolio_id = cube_id
                new_positions = client.get_current_positions()
                logger.info(f"持仓数量: {len(new_positions)} 只")

                if not client.last_fetch_ok:
                    logger.error(f"[{cube_id}] 没有拿到持仓数据，保留旧快照")
                    break

                if not new_positions:
                    logger.warning(f"[{cube_id}] 持仓列表为空，可能组合不存在或没有公开持仓")

                records = client.get_rebalancing_history()
                if records is None:
                    logger.error(f"[{cube_id}] 没有拿到调仓记录，保留旧快照")
                    break

                latest_rb = records[0] if records else None
                nav_info = parse_nav_from_rebalancing(latest_rb)
                if not nav_info.get("name"):
                    nav_info["name"] = cube_id
                logger.info(f"组合名称: {nav_info['name']}")

                last_rb_id = state.get(cube_id, {}).get("last_rb_id")
                latest_id = latest_rb.get("id") if latest_rb else None
                if last_rb_id is None:
                    logger.info(f"[{cube_id}] 首次记录调仓（ID={latest_id}），不补发历史调仓")
                    _save_cube_state(state, cube_id, new_positions, nav_info, latest_id)
                    state_changed = True
                    break

                fresh = [
                    record for record in records
                    if isinstance(record, dict) and (record.get("id") or 0) > last_rb_id
                ]
                fresh.sort(key=lambda record: record["id"])
                if not fresh:
                    logger.info(f"[{cube_id}] 调仓记录未变化（ID={latest_id}），跳过通知")
                    if cube_id in state:
                        state[cube_id]["last_check"] = datetime.now().isoformat()
                        state_changed = True
                    break

                for record in fresh:
                    rb_id = record.get("id")
                    status = record.get("status")
                    if status == "pending":
                        logger.info(f"[{cube_id}] 调仓尚未成交（ID={rb_id}），下一轮再看")
                        break
                    if status not in (None, "success"):
                        logger.info(f"[{cube_id}] 忽略状态为 {status} 的调仓（ID={rb_id}）")
                        _save_cube_state(state, cube_id, new_positions, nav_info, rb_id)
                        state_changed = True
                        continue

                    logger.info(f"[{cube_id}] 发现新调仓记录（ID={rb_id}，上次={last_rb_id}）")
                    changes = changes_from_rebalancing(record)
                    record_nav = parse_nav_from_rebalancing(record)
                    if not record_nav.get("name"):
                        record_nav["name"] = nav_info["name"]
                    if changes:
                        logger.info(f"[{cube_id}] 检测到 {len(changes)} 项主动调仓，准备发送通知")
                        title, content = build_markdown(cube_id, record_nav, changes)
                        ok = notifier.send_markdown(title, content, cube_id=cube_id)
                        if not ok:
                            logger.error(f"[{cube_id}] 通知发送失败，保留旧状态，下次重试")
                            break
                        logger.info(f"[{cube_id}] 通知发送成功")
                    else:
                        logger.info(f"[{cube_id}] 调仓记录没有主动仓位变化（ID={rb_id}）")
                    _save_cube_state(state, cube_id, new_positions, record_nav, rb_id)
                    state_changed = True
                    last_rb_id = rb_id

            except CookieExpired as exc:
                if _fail_cookie(state, notifier, client, str(exc)):
                    continue
                return False
            except Exception as e:
                logger.error(f"[{cube_id}] 异常: {e}")
                logger.debug(traceback.format_exc())
                notifier.send_text(f"⚠️ 雪球监控异常\n组合：{cube_id}\n错误：{e}")

            time.sleep(2)
            break

    if state_changed:
        _save_state(state)
    return False


def _check_config() -> bool:
    """检查配置完整性，有问题直接打印并返回 False"""
    ok = True
    if "你的token" in config.XUEQIU_COOKIE or not config.XUEQIU_COOKIE:
        print("❌ 未配置雪球 Cookie！请运行：uv run python -m xueqiu_monitor.login")
        ok = False
    if not config.MONITORED_CUBES or config.MONITORED_CUBES == ["ZH123456"]:
        print("❌ 未配置监控组合！请在 .env 文件或脚本顶部填写 MONITORED_CUBES")
        ok = False
    return ok


def _print_config_help() -> None:
    print("\n💡 配置方式（推荐使用 .env 文件）：")
    print("   在项目根目录创建 .env 文件，内容：")
    print("     XUEQIU_COOKIE=xq_a_token=xxx;u=xxx")
    print("     MONITORED_CUBES=ZH123456,ZH654321")
    print("     DINGTALK_ENABLED=true")
    print("     DINGTALK_WEBHOOK=https://oapi.dingtalk.com/robot/send?access_token=xxx")
    print("     TELEGRAM_ENABLED=true")
    print("     TELEGRAM_BOT_TOKEN=123456:abc")
    print("     TELEGRAM_CHAT_ID=123456789")
    print("     FEISHU_ENABLED=true")
    print("     FEISHU_APP_ID=cli_xxx")
    print("     FEISHU_APP_SECRET=xxx")
    print("     FEISHU_MODE=websocket")
    print("     FEISHU_RECEIVE_ID=oc_xxx")
    print("     CHECK_INTERVAL=300")


def main():
    print("=" * 60)
    print("  雪球组合变动监控 v2.1")
    print("=" * 60)

    config_ok = _check_config()
    notifier, notify_errors = build_notifier()
    for err in notify_errors:
        print(f"❌ {err}")
    if not config_ok:
        _print_config_help()
        sys.exit(1)

    sched = get_schedule_info()
    print(f"\n📌 监控组合: {', '.join(config.MONITORED_CUBES)}")
    print(f"⏱  交易时段间隔: {config.CHECK_INTERVAL} 秒｜休市间隔: {config.OFF_HOURS_INTERVAL} 秒")
    print(f"📅 当前时段: {sched['label']}（下次间隔 {sched['interval']} 秒）")
    if config.WEIGHT_CHANGE_THRESHOLD <= 0:
        print("📊 仓位变动: 有变化就通知")
    else:
        print(f"📊 仓位变动阈值: ≥ {config.WEIGHT_CHANGE_THRESHOLD}%")
    print(f"📤 通知渠道: {notifier.describe()}")
    print(f"📅 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    client = XueQiuClient(config.XUEQIU_COOKIE, config.MONITORED_CUBES[0])

    logger.info("首次检查...")
    if monitor_once(client, notifier):
        sys.exit(2)

    try:
        while True:
            sched = get_schedule_info()
            interval = int(sched["interval"])
            logger.info(f"当前时段「{sched['label']}」，等待 {interval} 秒后再次检查...")
            time.sleep(interval)
            if monitor_once(client, notifier):
                sys.exit(2)
    except KeyboardInterrupt:
        logger.info("监控已手动停止")
        print("\n👋 监控已停止")
