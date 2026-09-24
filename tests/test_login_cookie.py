"""登录后如何识别 Cookie，以及如何写回 .env。不打开浏览器。"""

import base64
import hashlib
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import dotenv_values

from login import (
    credentials_from_env,
    decrypt_chrome_cookie,
    logged_in_cookie_header,
    profile_cookie_header,
    sms_challenge_visible,
    upsert_env,
)


def _user_token(uid: int) -> str:
    body = base64.urlsafe_b64encode(json.dumps({"uid": uid, "exp": 1893456000}).encode()).decode().rstrip("=")
    return f"h.{body}.s"


def _encrypt_chrome(host: str, value: str) -> bytes:
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, dklen=16)
    plain = hashlib.sha256(host.encode()).digest() + value.encode()
    pad = 16 - (len(plain) % 16)
    plain += bytes([pad]) * pad
    encrypted = subprocess.run(
        ["openssl", "enc", "-e", "-aes-128-cbc", "-K", key.hex(), "-iv", (b" " * 16).hex(), "-nopad"],
        input=plain,
        capture_output=True,
        check=True,
    ).stdout
    return b"v10" + encrypted


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
        token = _user_token(100)
        cookies = [
            _cookie("other", "1", domain="example.com"),
            _cookie("xq_id_token", token),
            _cookie("extra", "keep"),
            _cookie("u", "100"),
            _cookie("xq_a_token", "token"),
            {"name": "empty", "value": "", "domain": ".xueqiu.com"},
        ]
        header = logged_in_cookie_header(cookies)
        assert header == f"xq_a_token=token;u=100;xq_id_token={token}"

    def test_rejects_guest_id_token(self):
        cookies = [
            _cookie("xq_a_token", "token"),
            _cookie("u", "100"),
            _cookie("xq_id_token", _user_token(-1)),
        ]
        assert logged_in_cookie_header(cookies) is None


class TestProfileCookie:
    def test_reads_encrypted_user_cookie_without_browser(self, tmp_path):
        host = ".xueqiu.com"
        token = _user_token(42)
        profile = tmp_path / "chrome"
        default = profile / "Default"
        default.mkdir(parents=True)
        database = default / "Cookies"
        connection = sqlite3.connect(database)
        connection.execute(
            "create table cookies (host_key text, name text, value text, encrypted_value blob, expires_utc integer)"
        )
        expires = int((time.time() + 3600 + 11644473600) * 1_000_000)
        rows = {
            "xq_a_token": "access",
            "u": "42",
            "xq_id_token": token,
            "acw_tc": "stale-waf",
        }
        for name, value in rows.items():
            connection.execute(
                "insert into cookies values (?, ?, '', ?, ?)",
                (host, name, _encrypt_chrome(host, value), expires),
            )
        connection.commit()
        connection.close()

        header = profile_cookie_header(profile)
        assert header == f"xq_a_token=access;u=42;xq_id_token={token}"
        assert decrypt_chrome_cookie(host, _encrypt_chrome(host, token)) == token


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


class _Locator:
    def __init__(self, visible: bool):
        self._visible = visible

    def count(self):
        return 1

    @property
    def first(self):
        return self

    def is_visible(self):
        return self._visible


class _Page:
    def __init__(self, visible_texts):
        self.visible_texts = visible_texts

    def get_by_text(self, text, exact=False):
        return _Locator(text in self.visible_texts)


class TestSmsChallenge:
    def test_visible_sms_marker(self):
        assert sms_challenge_visible(_Page({"短信验证码"})) is True

    def test_hidden_or_unrelated_text(self):
        assert sms_challenge_visible(_Page(set())) is False
        assert sms_challenge_visible(_Page({"验证码登录"})) is False


class TestCredentials:
    def test_strips_whitespace(self, monkeypatch):
        monkeypatch.setenv("XUEQIU_ACCOUNT", "  user  ")
        monkeypatch.setenv("XUEQIU_PASSWORD", "  secret  ")
        assert credentials_from_env() == ("user", "secret")
