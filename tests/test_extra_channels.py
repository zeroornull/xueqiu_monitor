"""新增通知渠道。HTTP 和 SMTP 都打到假对象，不访问外网。"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from xueqiu_monitor.notifiers import build_notifier

_KEYS = (
    "DINGTALK_ENABLED",
    "DINGTALK_WEBHOOK",
    "DINGTALK_SECRET",
    "AT_ALL",
    "TELEGRAM_ENABLED",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "FEISHU_ENABLED",
    "FEISHU_APP_ID",
    "FEISHU_APP_SECRET",
    "FEISHU_MODE",
    "FEISHU_RECEIVE_ID",
    "FEISHU_RECEIVE_ID_TYPE",
    "FEISHU_WEBHOOK_ENABLED",
    "FEISHU_WEBHOOK",
    "FEISHU_WEBHOOK_SECRET",
    "WECOM_ENABLED",
    "WECOM_WEBHOOK",
    "SLACK_ENABLED",
    "SLACK_WEBHOOK",
    "DISCORD_ENABLED",
    "DISCORD_WEBHOOK",
    "SMTP_ENABLED",
    "SMTP_HOST",
    "SMTP_PORT",
    "SMTP_USER",
    "SMTP_PASSWORD",
    "SMTP_FROM",
    "SMTP_TO",
    "SMTP_STARTTLS",
    "SMTP_SSL",
    "HTTP_WEBHOOK_ENABLED",
    "HTTP_WEBHOOK_URL",
    "HTTP_WEBHOOK_BEARER",
    "HTTP_WEBHOOK_EXTRA",
    "NTFY_ENABLED",
    "NTFY_SERVER",
    "NTFY_TOPIC",
    "NTFY_TOKEN",
    "NTFY_PRIORITY",
    "GOTIFY_ENABLED",
    "GOTIFY_SERVER",
    "GOTIFY_TOKEN",
    "GOTIFY_PRIORITY",
    "PUSHOVER_ENABLED",
    "PUSHOVER_USER",
    "PUSHOVER_TOKEN",
    "PUSHOVER_PRIORITY",
    "TEAMS_ENABLED",
    "TEAMS_WEBHOOK",
    "MATRIX_ENABLED",
    "MATRIX_HOMESERVER",
    "MATRIX_ROOM_ID",
    "MATRIX_TOKEN",
    "SERVERCHAN_ENABLED",
    "SERVERCHAN_SENDKEY",
    "PUSHPLUS_ENABLED",
    "PUSHPLUS_TOKEN",
    "PUSHPLUS_TOPIC",
    "PUSHPLUS_TEMPLATE",
    "BARK_ENABLED",
    "BARK_SERVER",
    "BARK_DEVICE_KEY",
    "BARK_SOUND",
    "BARK_GROUP",
    "WXPUSHER_ENABLED",
    "WXPUSHER_APP_TOKEN",
    "WXPUSHER_UIDS",
    "WXPUSHER_TOPIC_IDS",
    "PUSHDEER_ENABLED",
    "PUSHDEER_PUSHKEY",
    "PUSHDEER_SERVER",
)

_SPECS = [
    {
        "name": "Slack",
        "enable": "SLACK_ENABLED",
        "env": {"SLACK_WEBHOOK": "https://hooks.slack.test/a"},
        "method": "POST",
        "url": "https://hooks.slack.test/a",
        "json": {"text": "正文"},
        "response": {"ok": True},
    },
    {
        "name": "Discord",
        "enable": "DISCORD_ENABLED",
        "env": {"DISCORD_WEBHOOK": "https://discord.test/api/webhooks/1/abc"},
        "method": "POST",
        "url": "https://discord.test/api/webhooks/1/abc",
        "json": {"content": "正文"},
    },
    {
        "name": "Webhook",
        "enable": "HTTP_WEBHOOK_ENABLED",
        "env": {
            "HTTP_WEBHOOK_URL": "https://example.test/hook",
            "HTTP_WEBHOOK_BEARER": "token-1",
            "HTTP_WEBHOOK_EXTRA": '{"room":"ops"}',
        },
        "method": "POST",
        "url": "https://example.test/hook",
        "json": {"room": "ops", "title": "标题", "text": "正文"},
        "headers": {"Authorization": "Bearer token-1"},
    },
    {
        "name": "ntfy",
        "enable": "NTFY_ENABLED",
        "env": {"NTFY_SERVER": "https://ntfy.test", "NTFY_TOPIC": "alerts", "NTFY_TOKEN": "tk", "NTFY_PRIORITY": "4"},
        "method": "POST",
        "url": "https://ntfy.test/alerts",
        "data": "正文".encode(),
        "headers": {"Title": "标题", "Priority": "4", "Authorization": "Bearer tk"},
    },
    {
        "name": "Gotify",
        "enable": "GOTIFY_ENABLED",
        "env": {"GOTIFY_SERVER": "https://gotify.test", "GOTIFY_TOKEN": "app-token", "GOTIFY_PRIORITY": "8"},
        "method": "POST",
        "url": "https://gotify.test/message",
        "json": {"title": "标题", "message": "正文", "priority": 8},
        "headers": {"X-Gotify-Key": "app-token"},
    },
    {
        "name": "Pushover",
        "enable": "PUSHOVER_ENABLED",
        "env": {"PUSHOVER_USER": "user-key", "PUSHOVER_TOKEN": "api-token", "PUSHOVER_PRIORITY": "1"},
        "method": "POST",
        "url": "https://api.pushover.net/1/messages.json",
        "data": {"token": "api-token", "user": "user-key", "message": "正文", "title": "标题", "priority": 1},
        "response": {"status": 1},
    },
    {
        "name": "Teams",
        "enable": "TEAMS_ENABLED",
        "env": {"TEAMS_WEBHOOK": "https://teams.test/webhook"},
        "method": "POST",
        "url": "https://teams.test/webhook",
        "json_type": "message",
    },
    {
        "name": "Matrix",
        "enable": "MATRIX_ENABLED",
        "env": {
            "MATRIX_HOMESERVER": "https://matrix.test",
            "MATRIX_ROOM_ID": "!room:example.org",
            "MATRIX_TOKEN": "syt_token",
        },
        "method": "PUT",
        "url_contains": "/_matrix/client/v3/rooms/%21room%3Aexample.org/send/m.room.message/",
        "json": {"msgtype": "m.text", "body": "正文"},
        "headers": {"Authorization": "Bearer syt_token"},
    },
    {
        "name": "企业微信",
        "enable": "WECOM_ENABLED",
        "env": {"WECOM_WEBHOOK": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc"},
        "method": "POST",
        "url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=abc",
        "json": {"msgtype": "markdown", "markdown": {"content": "正文"}},
        "response": {"errcode": 0},
    },
    {
        "name": "飞书机器人",
        "enable": "FEISHU_WEBHOOK_ENABLED",
        "env": {"FEISHU_WEBHOOK": "https://open.feishu.cn/open-apis/bot/v2/hook/abc"},
        "method": "POST",
        "url": "https://open.feishu.cn/open-apis/bot/v2/hook/abc",
        "json_msg_type": "interactive",
        "response": {"code": 0},
    },
    {
        "name": "Server酱",
        "enable": "SERVERCHAN_ENABLED",
        "env": {"SERVERCHAN_SENDKEY": "SCT123"},
        "method": "POST",
        "url": "https://sctapi.ftqq.com/SCT123.send",
        "data": {"title": "标题", "desp": "正文"},
        "response": {"code": 0},
    },
    {
        "name": "PushPlus",
        "enable": "PUSHPLUS_ENABLED",
        "env": {"PUSHPLUS_TOKEN": "pp-token", "PUSHPLUS_TOPIC": "group", "PUSHPLUS_TEMPLATE": "markdown"},
        "method": "POST",
        "url": "https://www.pushplus.plus/send",
        "json": {"token": "pp-token", "title": "标题", "content": "正文", "template": "markdown", "topic": "group"},
        "response": {"code": 200},
    },
    {
        "name": "Bark",
        "enable": "BARK_ENABLED",
        "env": {"BARK_SERVER": "https://bark.test", "BARK_DEVICE_KEY": "device", "BARK_SOUND": "bell", "BARK_GROUP": "xq"},
        "method": "POST",
        "url": "https://bark.test/push",
        "json": {"device_key": "device", "title": "标题", "body": "正文", "sound": "bell", "group": "xq"},
        "response": {"code": 200},
    },
    {
        "name": "WxPusher",
        "enable": "WXPUSHER_ENABLED",
        "env": {"WXPUSHER_APP_TOKEN": "AT_1", "WXPUSHER_UIDS": "UID_a,UID_b", "WXPUSHER_TOPIC_IDS": "3"},
        "method": "POST",
        "url": "https://wxpusher.zjiecode.com/api/send/message",
        "json": {
            "appToken": "AT_1",
            "content": "正文",
            "summary": "标题",
            "contentType": 3,
            "uids": ["UID_a", "UID_b"],
            "topicIds": [3],
        },
        "response": {"code": 1000},
    },
    {
        "name": "PushDeer",
        "enable": "PUSHDEER_ENABLED",
        "env": {"PUSHDEER_PUSHKEY": "PDU1", "PUSHDEER_SERVER": "https://pushdeer.test"},
        "method": "POST",
        "url": "https://pushdeer.test/message/push",
        "json": {"pushkey": "PDU1", "text": "正文", "type": "markdown"},
        "response": {"code": 0},
    },
]


def _isolate(monkeypatch):
    for key in _KEYS:
        monkeypatch.delenv(key, raising=False)


def _apply(monkeypatch, spec, enabled="true"):
    _isolate(monkeypatch)
    monkeypatch.setenv(spec["enable"], enabled)
    if enabled == "true":
        for key, value in spec["env"].items():
            monkeypatch.setenv(key, value)


def _response(payload, ok=True, status=200):
    resp = MagicMock()
    resp.ok = ok
    resp.status_code = status
    resp.content = b"{}"
    resp.text = "ok"
    resp.json.return_value = payload
    return resp


def _channel(spec):
    channels, errors = build_notifier()
    found = [item for item in channels.channels if item.name == spec["name"]]
    return channels, errors, found


def _assert_call(spec, call):
    assert call.args[0] == spec["method"]
    url = call.args[1]
    if "url" in spec:
        assert url == spec["url"]
    if "url_contains" in spec:
        assert spec["url_contains"] in url
    if "json" in spec:
        assert call.kwargs["json"] == spec["json"]
    if "data" in spec:
        assert call.kwargs["data"] == spec["data"]
    if spec.get("json_type"):
        assert call.kwargs["json"]["type"] == spec["json_type"]
        assert call.kwargs["json"]["attachments"][0]["content"]["body"][0]["text"] == "正文"
    if spec.get("json_msg_type"):
        body = call.kwargs["json"]
        assert body["msg_type"] == spec["json_msg_type"]
        assert "正文" in body["card"]["elements"][0]["content"]
    for key, value in spec.get("headers", {}).items():
        assert call.kwargs["headers"][key] == value


@pytest.mark.parametrize("spec", _SPECS, ids=[item["name"] for item in _SPECS])
def test_enabled_channel_sends_expected_request(spec, monkeypatch):
    _apply(monkeypatch, spec)
    with patch("xueqiu_monitor.notifiers.base.requests.request", return_value=_response(spec.get("response", {}))) as req:
        channels, errors, found = _channel(spec)
        assert errors == []
        assert len(found) == 1
        assert found[0].send_markdown("标题", "正文", cube_id="ZH9") is True
    assert req.call_count == 1
    _assert_call(spec, req.call_args)
    assert channels.describe().find(spec["name"]) >= 0


@pytest.mark.parametrize("spec", _SPECS, ids=[item["name"] for item in _SPECS])
def test_disabled_channel_does_not_send(spec, monkeypatch):
    _apply(monkeypatch, spec, enabled="false")
    with patch("xueqiu_monitor.notifiers.base.requests.request") as req:
        _channels, errors, found = _channel(spec)
        assert errors == []
        assert found == []
        assert _channels.send_markdown("标题", "正文") is True
    req.assert_not_called()


@pytest.mark.parametrize("spec", _SPECS, ids=[item["name"] for item in _SPECS])
def test_missing_config_does_not_raise(spec, monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv(spec["enable"], "true")
    with patch("xueqiu_monitor.notifiers.base.requests.request") as req:
        channels, errors, found = _channel(spec)
    assert found == []
    assert errors
    assert channels.send_text("不会发出") is True
    req.assert_not_called()


@pytest.mark.parametrize("spec", _SPECS, ids=[item["name"] for item in _SPECS])
def test_http_error_is_isolated(spec, monkeypatch):
    _apply(monkeypatch, spec)
    bad = _response({}, ok=False, status=503)
    with patch("xueqiu_monitor.notifiers.base.requests.request", return_value=bad):
        _channels, _errors, found = _channel(spec)
        assert found[0].send_markdown("标题", "正文", cube_id="ZH9") is False


def test_one_http_failure_does_not_block_the_next_channel(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("SLACK_ENABLED", "true")
    monkeypatch.setenv("SLACK_WEBHOOK", "https://hooks.slack.test/a")
    monkeypatch.setenv("DISCORD_ENABLED", "true")
    monkeypatch.setenv("DISCORD_WEBHOOK", "https://discord.test/api/webhooks/1/abc")
    bad = _response({}, ok=False, status=500)
    good = _response({})
    with patch("xueqiu_monitor.notifiers.base.requests.request", side_effect=[bad, good]) as req:
        channels, errors = build_notifier()
        assert errors == []
        assert channels.send_markdown("标题", "正文", "ZH1") is False
    assert req.call_count == 2


def test_cooldown_skips_the_second_send(monkeypatch):
    spec = _SPECS[0]
    _apply(monkeypatch, spec)
    with patch("xueqiu_monitor.notifiers.base.requests.request", return_value=_response({"ok": True})) as req:
        _channels, _errors, found = _channel(spec)
        assert found[0].send_markdown("标题", "正文", cube_id="ZH1") is True
        assert found[0].send_markdown("标题", "正文", cube_id="ZH1") is True
    assert req.call_count == 1


def test_invalid_webhook_extra_does_not_raise(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("HTTP_WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("HTTP_WEBHOOK_URL", "https://example.test/hook")
    monkeypatch.setenv("HTTP_WEBHOOK_EXTRA", "[1, 2]")
    channels, errors = build_notifier()
    assert channels.channels == []
    assert any("HTTP_WEBHOOK_EXTRA" in item for item in errors)


def test_smtp_sends_message(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("SMTP_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_PORT", "587")
    monkeypatch.setenv("SMTP_USER", "bot")
    monkeypatch.setenv("SMTP_PASSWORD", "secret")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SMTP_TO", "a@example.com,b@example.com")
    monkeypatch.setenv("SMTP_STARTTLS", "true")
    client = MagicMock()
    with patch("xueqiu_monitor.notifiers.smtp.smtplib.SMTP", return_value=client) as smtp:
        channels, errors = build_notifier()
        assert errors == []
        assert channels.channels[0].name == "邮件"
        assert channels.send_markdown("标题", "正文", "ZH1") is True
    smtp.assert_called_once_with("smtp.test", 587, timeout=15)
    client.starttls.assert_called_once()
    client.login.assert_called_once_with("bot", "secret")
    message = client.send_message.call_args.args[0]
    assert message["Subject"] == "标题"
    assert message["From"] == "bot@example.com"
    assert message["To"] == "a@example.com, b@example.com"
    assert message.get_content().strip() == "正文"


def test_smtp_disabled_does_not_connect(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("SMTP_ENABLED", "false")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SMTP_TO", "a@example.com")
    with patch("xueqiu_monitor.notifiers.smtp.smtplib.SMTP") as smtp:
        channels, errors = build_notifier()
        assert errors == []
        assert channels.send_text("忽略") is True
    smtp.assert_not_called()


def test_smtp_missing_config_does_not_raise(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("SMTP_ENABLED", "true")
    channels, errors = build_notifier()
    assert channels.channels == []
    assert any("SMTP_HOST" in item for item in errors)
    assert channels.send_markdown("标题", "正文") is True


def test_smtp_error_is_isolated(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("SMTP_ENABLED", "true")
    monkeypatch.setenv("SMTP_HOST", "smtp.test")
    monkeypatch.setenv("SMTP_FROM", "bot@example.com")
    monkeypatch.setenv("SMTP_TO", "a@example.com")
    monkeypatch.setenv("SMTP_SSL", "true")
    monkeypatch.setenv("SMTP_STARTTLS", "false")
    client = MagicMock()
    client.send_message.side_effect = OSError("down")
    with patch("xueqiu_monitor.notifiers.smtp.smtplib.SMTP_SSL", return_value=client):
        channels, errors = build_notifier()
        assert errors == []
        assert channels.send_markdown("标题", "正文", "ZH1") is False
    client.quit.assert_called()


def test_feishu_app_and_webhook_can_both_be_enabled(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setenv("FEISHU_ENABLED", "true")
    monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
    monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
    monkeypatch.setenv("FEISHU_RECEIVE_ID", "oc_1")
    monkeypatch.setenv("FEISHU_MODE", "websocket")
    monkeypatch.setenv("FEISHU_WEBHOOK_ENABLED", "true")
    monkeypatch.setenv("FEISHU_WEBHOOK", "https://open.feishu.cn/open-apis/bot/v2/hook/abc")
    channels, errors = build_notifier()
    assert errors == []
    assert channels.describe() == "飞书、飞书机器人"
