"""通知渠道组装与发送。请求全部打到假响应，不访问外网。"""

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import xueqiu_monitor.notifiers.dingtalk as dingtalk
import xueqiu_monitor.notifiers.feishu as feishu
import xueqiu_monitor.notifiers.telegram as telegram
from xueqiu_monitor.notifiers import Notifier, _in_cooldown, build_notifier
from xueqiu_monitor.notifiers.dingtalk import DingTalkNotifier
from xueqiu_monitor.notifiers.feishu import FeishuNotifier, _feishu_target
from xueqiu_monitor.notifiers.slack import SlackNotifier
from xueqiu_monitor.notifiers.telegram import TelegramNotifier

_NOTIFY_KEYS = (
    "DINGTALK_ENABLED",
    "DINGTALK_WEBHOOK",
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
    "DINGTALK_SECRET",
    "FEISHU_WEBHOOK_ENABLED",
    "WECOM_ENABLED",
    "SLACK_ENABLED",
    "DISCORD_ENABLED",
    "SMTP_ENABLED",
    "HTTP_WEBHOOK_ENABLED",
    "NTFY_ENABLED",
    "GOTIFY_ENABLED",
    "PUSHOVER_ENABLED",
    "TEAMS_ENABLED",
    "MATRIX_ENABLED",
    "SERVERCHAN_ENABLED",
    "PUSHPLUS_ENABLED",
    "BARK_ENABLED",
    "WXPUSHER_ENABLED",
    "PUSHDEER_ENABLED",
)


def _isolate_env(monkeypatch):
    for key in _NOTIFY_KEYS:
        monkeypatch.delenv(key, raising=False)


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


class TestBuildNotifier:
    def test_none_enabled(self, monkeypatch):
        _isolate_env(monkeypatch)
        channels, errors = build_notifier()
        assert channels.describe() == "未启用"
        assert errors == []
        assert channels.send_text("忽略") is True

    def test_dingtalk_missing_webhook(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("DINGTALK_ENABLED", "true")
        channels, errors = build_notifier()
        assert channels.describe() == "未启用"
        assert errors == ["已启用钉钉，但未配置有效的 DINGTALK_WEBHOOK"]

    def test_dingtalk_placeholder_webhook(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("DINGTALK_ENABLED", "TRUE")
        monkeypatch.setenv("DINGTALK_WEBHOOK", "https://oapi.dingtalk.com/robot/send?access_token=你的access_token")
        _, errors = build_notifier()
        assert errors == ["已启用钉钉，但未配置有效的 DINGTALK_WEBHOOK"]

    def test_telegram_missing_chat(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("TELEGRAM_ENABLED", "true")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        _, errors = build_notifier()
        assert "TELEGRAM_CHAT_ID" in errors[0]

    def test_feishu_bad_mode(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("FEISHU_ENABLED", "true")
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "oc_1")
        monkeypatch.setenv("FEISHU_MODE", "webhook")
        _, errors = build_notifier()
        assert errors == ["FEISHU_MODE 只支持 websocket"]

    def test_feishu_missing_receive_id(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("FEISHU_ENABLED", "true")
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
        monkeypatch.setenv("FEISHU_MODE", "websocket")
        _, errors = build_notifier()
        assert "FEISHU_RECEIVE_ID" in errors[0]

    def test_all_channels(self, monkeypatch):
        _isolate_env(monkeypatch)
        monkeypatch.setenv("DINGTALK_ENABLED", "true")
        monkeypatch.setenv("DINGTALK_WEBHOOK", "https://example.test/hook")
        monkeypatch.setenv("AT_ALL", "true")
        monkeypatch.setenv("TELEGRAM_ENABLED", "true")
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "99")
        monkeypatch.setenv("FEISHU_ENABLED", "true")
        monkeypatch.setenv("FEISHU_APP_ID", "cli_test")
        monkeypatch.setenv("FEISHU_APP_SECRET", "secret")
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "ou_user")
        monkeypatch.setenv("FEISHU_MODE", "websocket")
        channels, errors = build_notifier()
        assert errors == []
        assert channels.describe() == "钉钉、Telegram、飞书"
        assert channels.channels[0].at_all is True
        assert channels.channels[2].receive_id_type == "open_id"


class TestFeishuTarget:
    def test_infer_open_id(self, monkeypatch):
        monkeypatch.delenv("FEISHU_RECEIVE_ID_TYPE", raising=False)
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "ou_abc")
        assert _feishu_target() == ("ou_abc", "open_id")

    def test_infer_union_id(self, monkeypatch):
        monkeypatch.delenv("FEISHU_RECEIVE_ID_TYPE", raising=False)
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "on_abc")
        assert _feishu_target() == ("on_abc", "union_id")

    def test_explicit_user_id(self, monkeypatch):
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "employee1")
        monkeypatch.setenv("FEISHU_RECEIVE_ID_TYPE", "user_id")
        assert _feishu_target() == ("employee1", "user_id")

    def test_default_chat_id(self, monkeypatch):
        monkeypatch.delenv("FEISHU_RECEIVE_ID_TYPE", raising=False)
        monkeypatch.setenv("FEISHU_RECEIVE_ID", "oc_group")
        assert _feishu_target() == ("oc_group", "chat_id")


class TestSend:
    def test_cooldown_skips_empty_cube(self):
        assert _in_cooldown({"ZH1": time.time()}, "") is False

    def test_dingtalk_markdown_and_cooldown(self):
        bot = DingTalkNotifier("https://example.test/hook", at_all=True)
        with patch.object(dingtalk.requests, "post", return_value=_response({"errcode": 0})) as post:
            assert bot.send_markdown("标题", "正文", cube_id="ZH1") is True
            assert bot.send_markdown("标题", "正文", cube_id="ZH1") is True
        assert post.call_count == 1
        payload = post.call_args.kwargs["json"]
        assert payload["msgtype"] == "markdown"
        assert payload["at"]["isAtAll"] is True

    def test_dingtalk_failure(self):
        bot = DingTalkNotifier("https://example.test/hook")
        with patch.object(dingtalk.requests, "post", return_value=_response({"errcode": 310000})):
            assert bot.send_text("失败") is False

    def test_telegram_html(self):
        bot = TelegramNotifier("123:abc", "99")
        with patch.object(telegram.requests, "post", return_value=_response({"ok": True})) as post:
            assert bot.send_markdown("标题", "## 变动\n**茅台**", cube_id="ZH1") is True
        body = post.call_args.kwargs["json"]
        assert body["chat_id"] == "99"
        assert "<b>变动</b>" in body["text"]
        assert "<b>茅台</b>" in body["text"]

    def test_telegram_request_error_hides_body(self):
        bot = TelegramNotifier("123:abc", "99")
        with patch.object(telegram.requests, "post", side_effect=TimeoutError("slow")):
            assert bot.send_text("超时") is False

    def test_feishu_text_uses_cached_token(self):
        bot = FeishuNotifier("cli_test", "secret", "employee1", "user_id")
        token = _response({"code": 0, "tenant_access_token": "t-1", "expire": 7200})
        sent = _response({"code": 0, "data": {"message_id": "om_1"}})
        with patch.object(feishu.requests, "post", side_effect=[token, sent, sent]) as post:
            assert bot.send_text("测试") is True
            assert bot.send_text("再来一条") is True
        assert post.call_count == 3
        assert post.call_args_list[0].kwargs["json"]["app_id"] == "cli_test"
        assert "tenant_access_token" in post.call_args_list[0].args[0]
        message = post.call_args_list[1].kwargs["json"]
        assert message["receive_id"] == "employee1"
        assert message["msg_type"] == "text"
        assert json.loads(message["content"])["text"] == "测试"
        assert post.call_args_list[1].kwargs["params"]["receive_id_type"] == "user_id"

    def test_feishu_markdown_card(self):
        bot = FeishuNotifier("cli_test", "secret", "oc_1", "chat_id")
        token = _response({"code": 0, "tenant_access_token": "t-1", "expire": 7200})
        sent = _response({"code": 0})
        with patch.object(feishu.requests, "post", side_effect=[token, sent]) as post:
            assert bot.send_markdown("标题", "## 明细\n> 引用", cube_id="") is True
        content = json.loads(post.call_args.kwargs["json"]["content"])
        assert content["header"]["title"]["content"] == "标题"
        assert "**明细**" in content["elements"][0]["content"]
        assert ">" not in content["elements"][0]["content"]

    def test_feishu_token_failure(self):
        bot = FeishuNotifier("cli_test", "secret", "oc_1", "chat_id")
        with patch.object(feishu.requests, "post", return_value=_response({"code": 99991663, "msg": "invalid"})):
            assert bot.send_text("不会发出") is False

    def test_aggregate_failure(self):
        ok = MagicMock()
        ok.send_markdown.return_value = True
        bad = MagicMock()
        bad.send_markdown.return_value = False
        bad.send_text.return_value = False
        note = Notifier([ok, bad])
        assert note.send_markdown("t", "c", "ZH1") is False
        assert note.send_text("c") is False
        ok.send_markdown.assert_called_once()

    def test_dingtalk_secret_is_added_to_the_url(self, monkeypatch):
        monkeypatch.setattr(dingtalk.time, "time", lambda: 1600000000)
        bot = DingTalkNotifier("https://example.test/hook?access_token=abc", secret="SEC123")
        with patch.object(dingtalk.requests, "post", return_value=_response({"errcode": 0})) as post:
            assert bot.send_text("正文") is True
        url = post.call_args.args[0]
        assert url.startswith("https://example.test/hook?access_token=abc&timestamp=1600000000000&sign=")
        assert dingtalk.sign("SEC123", "1600000000000") in url


def _sent(payload):
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.content = b"{}"
    resp.text = "ok"
    resp.json.return_value = payload
    return resp


def _rb_channel(name):
    if name == "dingtalk":
        channel = DingTalkNotifier("https://example.test/hook")
        return channel, "xueqiu_monitor.notifiers.dingtalk.requests.post", {"errcode": 0}
    if name == "telegram":
        channel = TelegramNotifier("123:abc", "99")
        return channel, "xueqiu_monitor.notifiers.telegram.requests.post", {"ok": True}
    if name == "feishu":
        channel = FeishuNotifier("cli_test", "secret", "oc_1", "chat_id")
        channel._token = "t-1"
        channel._token_until = time.time() + 3600
        return channel, "xueqiu_monitor.notifiers.feishu.requests.post", {"code": 0}
    channel = SlackNotifier("https://slack.test/hook")
    return channel, "xueqiu_monitor.notifiers.base.requests.request", {}


@pytest.mark.parametrize("name", ["dingtalk", "telegram", "feishu", "slack"])
def test_distinct_rb_ids_both_send(name):
    channel, target, payload = _rb_channel(name)
    with patch(target, return_value=_sent(payload)) as req:
        assert channel.send_markdown("标题", "甲", cube_id="ZH1", rb_id=2) is True
        assert channel.send_markdown("标题", "乙", cube_id="ZH1", rb_id=3) is True
    assert req.call_count == 2


@pytest.mark.parametrize("name", ["dingtalk", "telegram", "feishu", "slack"])
def test_same_rb_id_skips_the_second_send(name):
    channel, target, payload = _rb_channel(name)
    with patch(target, return_value=_sent(payload)) as req:
        assert channel.send_markdown("标题", "甲", cube_id="ZH1", rb_id=2) is True
        assert channel.send_markdown("标题", "甲再发", cube_id="ZH1", rb_id=2) is True
    assert req.call_count == 1
