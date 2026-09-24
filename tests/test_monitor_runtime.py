"""监控运行时：状态、接口解析、过期处理和一轮检查。不请求雪球。"""

import base64
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import xueqiu_monitor as xm
from xueqiu_monitor import (
    CookieExpired,
    XueQiuClient,
    _auth_failure_reason,
    _check_config,
    _check_token_expiry,
    _cookie_already_failed,
    _is_user_id_token,
    _load_state,
    _save_cube_state,
    _save_state,
    _stop_for_cookie,
    _token_state,
    monitor_once,
    parse_nav_from_rebalancing,
)


def _jwt(payload: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def _response(status, payload=None, bad_json=False):
    resp = MagicMock()
    resp.status_code = status
    if bad_json:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = payload
    resp.raise_for_status.side_effect = None
    return resp


def _client(cookie="xq_a_token=abc;u=9;acw_tc=drop"):
    with patch.object(XueQiuClient, "_init_session"):
        client = XueQiuClient(cookie, "zh1")
    client._init_session = lambda: None
    return client


class _Notifier:
    def __init__(self, ok=True):
        self.ok = ok
        self.markdown = []
        self.texts = []

    def send_markdown(self, title, content, cube_id=""):
        self.markdown.append((title, content, cube_id))
        return self.ok

    def send_text(self, content):
        self.texts.append(content)
        return self.ok


class TestAuthAndNav:
    def test_http_status(self):
        assert _auth_failure_reason(_response(401)) == "HTTP 401"
        assert _auth_failure_reason(_response(403)) is None
        assert _auth_failure_reason(_response(403, {"error_description": "请先登录"})) == "请先登录"
        assert _auth_failure_reason(_response(400, {"error_description": "参数错误"})) is None

    def test_login_required_body(self):
        assert _auth_failure_reason(_response(200, {"error_code": "10022"})) == "error_code 10022"
        reason = _auth_failure_reason(_response(200, {"error_code": "400016", "error_description": "请先登录"}))
        assert reason == "请先登录"
        assert _auth_failure_reason(_response(200, ["nope"])) is None
        assert _auth_failure_reason(_response(200, bad_json=True)) is None

    def test_parse_nav(self):
        assert parse_nav_from_rebalancing(None) == {"name": ""}
        assert parse_nav_from_rebalancing({"cube_name": "直接名称"}) == {"name": "直接名称"}
        record = {"rebalancing_histories": [{"cube_name": "历史名称"}]}
        assert parse_nav_from_rebalancing(record) == {"name": "历史名称"}

    def test_check_config(self, capsys, monkeypatch):
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=你的token")
        monkeypatch.setattr(xm, "MONITORED_CUBES", ["ZH123456"])
        assert _check_config() is False
        captured = capsys.readouterr().out
        assert "Cookie" in captured
        assert "监控组合" in captured

        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=abc;u=1")
        monkeypatch.setattr(xm, "MONITORED_CUBES", ["ZH999999"])
        assert _check_config() is True


class TestStateAndCookie:
    def test_token_state_resets_when_cookie_changes(self, monkeypatch):
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=one;u=1")
        state = {"_token": {"hash": "stale", "auth_failed": True, "notified_expiry": True}}
        fresh = _token_state(state)
        assert fresh["hash"]
        assert "auth_failed" not in fresh
        assert _cookie_already_failed(state) is False

        fresh["auth_failed"] = True
        assert _cookie_already_failed(state) is True

    def test_load_and_save_roundtrip(self, tmp_path, monkeypatch):
        path = tmp_path / "state.json"
        monkeypatch.setattr(xm, "_STATE_FILE", str(path))
        assert _load_state() == {}
        path.write_text("{", encoding="utf-8")
        assert _load_state() == {}

        state = {}
        _save_cube_state(state, "ZH1", [{"symbol": "SH600519"}], {"name": "组合"}, 7)
        _save_state(state)
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert loaded["ZH1"]["last_rb_id"] == 7
        assert loaded["ZH1"]["positions"][0]["symbol"] == "SH600519"

    def test_expiry_warning_once(self, monkeypatch):
        expiry = time.time() + 10 * 3600
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", f"xq_a_token=abc_{int(expiry)}")
        note = _Notifier()
        state = {}
        assert _check_token_expiry(state, note) is True
        assert note.markdown[0][0] == "雪球 Cookie 即将过期"
        assert state["_token"]["notified_expiry"] is True
        assert _check_token_expiry(state, note) is False
        assert len(note.markdown) == 1

    def test_expiry_outside_window_is_silent(self, monkeypatch):
        expiry = time.time() + 48 * 3600
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", f"xq_a_token=abc_{int(expiry)}")
        note = _Notifier()
        assert _check_token_expiry({}, note) is False
        assert note.markdown == []

    def test_stop_retries_failed_notice(self, tmp_path, monkeypatch):
        monkeypatch.setattr(xm, "_STATE_FILE", str(tmp_path / "state.json"))
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=abc;u=1")
        note = _Notifier(ok=False)
        state = {}
        _stop_for_cookie(state, note, "HTTP 401")
        assert state["_token"]["notify_pending"] is True
        _stop_for_cookie(state, note, "HTTP 401")
        assert len(note.markdown) == 2

        note.ok = True
        _stop_for_cookie(state, note, "HTTP 401")
        assert state["_token"]["notify_pending"] is False
        _stop_for_cookie(state, note, "HTTP 401")
        assert len(note.markdown) == 3
        assert "auth_failed" not in state["_token"]


class TestClientParsing:
    def test_waf_page_cannot_replace_user_token(self):
        client = _client("xq_a_token=abc;u=9;xq_id_token=" + _jwt({"uid": 9, "exp": 1893456000}))
        assert _is_user_id_token(client.session.cookies.get("xq_id_token"))
        previous = client._auth_cookie_values()
        client.session.cookies.set("xq_id_token", _jwt({"uid": -1, "exp": 1893456000}), domain=".xueqiu.com", path="/")
        client.session.cookies.set("xq_is_login", "", domain=".xueqiu.com", path="/")
        client._restore_user_cookies(previous)
        assert client.session.cookies.get("xq_id_token") == previous["xq_id_token"]
        assert _is_user_id_token(client.session.cookies.get("xq_id_token"))

    def test_keeps_only_auth_cookies(self):
        client = _client()
        names = {cookie.name for cookie in client.session.cookies}
        assert names == {"xq_a_token", "u"}
        assert client.portfolio_id == "ZH1"

    def test_current_then_skip_zero_weight(self):
        client = _client()
        payload = {
            "last_rb": {
                "holdings": [
                    {"stock_symbol": "sh600519", "stock_name": "贵州茅台", "weight": 10, "price": 1},
                    {"symbol": "SZ000001", "name": "平安银行", "target_weight": 0, "price": 2},
                ]
            }
        }
        with patch.object(client, "_get", return_value=payload):
            positions = client.get_current_positions()
        assert client.last_fetch_ok is True
        assert positions == [{
            "symbol": "SH600519",
            "name": "贵州茅台",
            "weight": 10.0,
            "prev_weight": 0.0,
            "price": 1.0,
        }]

    def test_falls_back_to_history(self):
        client = _client()
        history = {
            "list": [{
                "rebalancing_histories": [
                    {"symbol": "SZ002594", "name": "比亚迪", "weight": 8, "prev_weight": 5, "price": 250}
                ]
            }]
        }
        with patch.object(client, "_get", side_effect=[None, None, history]) as get:
            positions = client.get_current_positions()
        assert get.call_count == 3
        assert positions[0]["symbol"] == "SZ002594"
        assert positions[0]["prev_weight"] == 5.0

    def test_all_sources_fail(self):
        client = _client()
        with patch.object(client, "_get", return_value=None):
            assert client.get_current_positions() == []
        assert client.last_fetch_ok is False

    def test_get_raises_on_auth_failure(self):
        client = _client()
        client.session.get = MagicMock(return_value=_response(401))
        try:
            client._get("https://xueqiu.com/cubes/rebalancing/current.json")
        except CookieExpired as exc:
            assert str(exc) == "HTTP 401"
        else:
            raise AssertionError("401 应该中断请求")

    def test_waf_403_refreshes_and_retries(self):
        client = _client()
        client.session.cookies.set("acw_tc", "stale", domain="xueqiu.com", path="/")
        ok = _response(200, {"last_rb": {"holdings": []}})
        blocked = _response(403)
        blocked.json.side_effect = ValueError("html")
        client.session.get = MagicMock(side_effect=[blocked, ok])
        with patch.object(client, "_refresh_waf", wraps=client._refresh_waf):
            assert client._get("https://xueqiu.com/cubes/rebalancing/current.json") == {"last_rb": {"holdings": []}}
        assert client.session.get.call_count == 2

    def test_get_returns_none_on_http_error(self):
        client = _client()
        resp = _response(500, {"ok": False})
        resp.raise_for_status.side_effect = xm.requests.exceptions.HTTPError("500")
        client.session.get = MagicMock(return_value=resp)
        assert client._get("https://xueqiu.com/missing") is None

    def test_latest_rebalancing(self):
        client = _client()
        with patch.object(client, "_get", return_value={"list": [{"id": 3}]}) as get:
            assert client.get_latest_rebalancing()["id"] == 3
        assert "history.json" in get.call_args.args[0]


class TestMonitorOnce:
    def _patch_common(self, monkeypatch, tmp_path):
        monkeypatch.setattr(xm, "_STATE_FILE", str(tmp_path / "state.json"))
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=abc;u=1")
        monkeypatch.setattr(xm, "MONITORED_CUBES", ["ZH1"])
        monkeypatch.setattr(xm.time, "sleep", lambda _seconds: None)

    def test_saves_when_positions_unchanged(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        positions = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1.0}]
        _save_state({"ZH1": {"positions": positions, "last_rb_id": None, "nav": {"name": "旧名"}}})
        client = _client()
        client.get_current_positions = MagicMock(return_value=positions)
        client.last_fetch_ok = True
        client.get_latest_rebalancing = MagicMock(return_value={"id": 1, "cube_name": "组合"})
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert note.markdown == []
        saved = _load_state()
        assert saved["ZH1"]["last_rb_id"] == 1
        assert saved["ZH1"]["nav"]["name"] == "组合"

    def test_notifies_and_skips_same_rebalance(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        old = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1.0}]
        _save_state({"ZH1": {"positions": old, "last_rb_id": 1, "nav": {"name": "组合"}}})
        client = _client()
        new = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 12.0, "price": 1.0}]
        client.get_current_positions = MagicMock(return_value=new)
        client.last_fetch_ok = True
        client.get_latest_rebalancing = MagicMock(return_value={"id": 2, "cube_name": "组合"})
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert note.markdown[0][2] == "ZH1"
        assert _load_state()["ZH1"]["last_rb_id"] == 2

        client.get_latest_rebalancing = MagicMock(return_value={"id": 2, "cube_name": "组合"})
        assert monitor_once(client, note) is False
        assert len(note.markdown) == 1

    def test_failed_notify_keeps_old_snapshot(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        old = [{"symbol": "SH600519", "name": "贵州茅台", "weight": 10.0, "price": 1.0}]
        _save_state({"ZH1": {"positions": old, "last_rb_id": 1}})
        client = _client()
        client.get_current_positions = MagicMock(return_value=[])
        client.last_fetch_ok = True
        client.get_latest_rebalancing = MagicMock(return_value={"id": 2})
        note = _Notifier(ok=False)
        assert monitor_once(client, note) is False
        assert _load_state()["ZH1"]["positions"] == old

    def test_fetch_failure_keeps_snapshot(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        _save_state({"ZH1": {"positions": [{"symbol": "SH600519"}], "last_rb_id": 1}})
        client = _client()
        client.get_current_positions = MagicMock(return_value=[])
        client.last_fetch_ok = False
        client.get_latest_rebalancing = MagicMock()
        assert monitor_once(client, _Notifier()) is False
        client.get_latest_rebalancing.assert_not_called()
        assert _load_state()["ZH1"]["last_rb_id"] == 1

    def test_past_expiry_still_requests(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(xm, "XUEQIU_COOKIE", "xq_a_token=abc_1735660800")
        monkeypatch.setattr(xm, "_attempt_relogin", lambda client: "failed")
        client = _client()
        client.get_current_positions = MagicMock(return_value=[])
        client.last_fetch_ok = False
        note = _Notifier()
        assert monitor_once(client, note) is False
        client.get_current_positions.assert_called_once()
        assert note.markdown == []

    def test_auth_error_keeps_running(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(xm, "_attempt_relogin", lambda client: "unavailable")
        client = _client()
        client.get_current_positions = MagicMock(side_effect=CookieExpired("HTTP 403"))
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert note.markdown[0][0] == "雪球请求被拒绝"
        assert "30 天" in note.markdown[0][1]
        assert monitor_once(client, note) is False
        assert len(note.markdown) == 1
        assert "auth_failed" not in _load_state().get("_token", {})

    def test_relogin_retries_fetch(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        client = _client()
        calls = {"n": 0}

        def positions():
            calls["n"] += 1
            if calls["n"] == 1:
                raise CookieExpired("HTTP 401")
            client.last_fetch_ok = True
            return []

        def relogin(target):
            xm.XUEQIU_COOKIE = "xq_a_token=fresh;u=2"
            return "ok"

        monkeypatch.setattr(xm, "_attempt_relogin", relogin)
        client.get_current_positions = positions
        client.get_latest_rebalancing = MagicMock(return_value={"id": 1, "cube_name": "组合"})
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert calls["n"] == 2
        assert note.markdown == []

    def test_auth_error_during_fetch_keeps_running(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        monkeypatch.setattr(xm, "_attempt_relogin", lambda client: "failed")
        client = _client()
        client.get_current_positions = MagicMock(side_effect=CookieExpired("HTTP 403"))
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert "HTTP 403" in note.markdown[0][1]

    def test_unexpected_error_sends_text(self, monkeypatch, tmp_path):
        self._patch_common(monkeypatch, tmp_path)
        client = _client()
        client.get_current_positions = MagicMock(side_effect=RuntimeError("boom"))
        note = _Notifier()
        assert monitor_once(client, note) is False
        assert "boom" in note.texts[0]
