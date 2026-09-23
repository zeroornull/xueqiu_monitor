"""登录后如何识别 Cookie，以及如何写回 .env。不打开浏览器。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import dotenv_values

from login import credentials_from_env, logged_in_cookie_header, upsert_env


def _cookie(name, value, domain=".xueqiu.com"):
    return {"name": name, "value": value, "domain": domain}


class TestLoggedInCookie:
    def test_guest_uid_matches_device(self):
        cookies = [
            _cookie("xq_a_token", "guest"),
            _cookie("u", "device-1"),
            _cookie("cookiesu", "device-1"),
        ]
        assert logged_in_cookie_header(cookies) is None

    def test_missing_token(self):
        cookies = [_cookie("u", "100")]
        assert logged_in_cookie_header(cookies) is None

    def test_ignores_other_domains_and_orders_preferred_names(self):
        cookies = [
            _cookie("other", "1", domain="example.com"),
            _cookie("xq_id_token", "jwt"),
            _cookie("extra", "keep"),
            _cookie("u", "100"),
            _cookie("xq_a_token", "token"),
            {"name": "empty", "value": "", "domain": ".xueqiu.com"},
        ]
        header = logged_in_cookie_header(cookies)
        assert header == "xq_a_token=token;u=100;xq_id_token=jwt;extra=keep"


class TestUpsertEnv:
    def test_replaces_existing_key_and_quotes_special_characters(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text('XUEQIU_COOKIE=old\nOTHER=1\n', encoding="utf-8")
        upsert_env(path, "XUEQIU_COOKIE", 'a=b"c\\d')
        assert dotenv_values(path)["XUEQIU_COOKIE"] == 'a=b"c\\d'
        assert dotenv_values(path)["OTHER"] == "1"

    def test_appends_missing_key(self, tmp_path):
        path = tmp_path / ".env"
        path.write_text("OTHER=1", encoding="utf-8")
        upsert_env(path, "XUEQIU_ACCOUNT", "user@example.com")
        assert path.read_text(encoding="utf-8") == 'OTHER=1\nXUEQIU_ACCOUNT="user@example.com"\n'

    def test_rejects_newline(self, tmp_path):
        path = tmp_path / ".env"
        try:
            upsert_env(path, "XUEQIU_COOKIE", "a\nb")
        except ValueError as exc:
            assert "换行" in str(exc)
        else:
            raise AssertionError("含换行的值应该被拒绝")


class TestCredentials:
    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("XUEQIU_ACCOUNT", "  user  ")
        monkeypatch.setenv("XUEQIU_PASSWORD", "  secret  ")
        assert credentials_from_env() == ("user", "secret")
