"""用 .env 里的账号密码登录雪球，并把 Cookie 写回 .env。"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"
_PROFILE_DIR = Path(__file__).resolve().parent / ".xueqiu-chrome"
_LOGIN_URL = "https://xueqiu.com/"
_TIMEOUT_SECONDS = 300
_AUTO_TIMEOUT_SECONDS = 45
# 风控 Cookie（acw_tc、ssxmod_itna）绑在当次浏览器会话上，写进 .env 再重放会 400/403。
_PREFERRED = ("xq_a_token", "u", "xq_r_token", "xq_id_token", "xqat", "xq_is_login")
# 只认短信挑战。密码页旁边的「验证码登录」标签不算。
_SMS_MARKERS = ("短信验证码", "验证码已发送", "请输入短信")


@dataclass(frozen=True)
class LoginResult:
    status: str  # ok / sms / failed
    cookie: str | None = None
    message: str = ""


def logged_in_cookie_header(cookies: list[dict]) -> str | None:
    """已登录时返回 Cookie 头。游客也有 xq_a_token 和 u，但 u 等于设备号 cookiesu。"""
    jar: dict[str, str] = {}
    for cookie in cookies:
        domain = cookie.get("domain") or ""
        name = cookie.get("name") or ""
        value = cookie.get("value")
        if "xueqiu.com" not in domain or not name or not value:
            continue
        jar[name] = value
    uid = jar.get("u")
    device = jar.get("cookiesu")
    if not jar.get("xq_a_token") or not uid or (device and uid == device):
        return None
    names = [name for name in _PREFERRED if jar.get(name)]
    if not _is_user_id_token(jar.get("xq_id_token")):
        return None
    return ";".join(f"{name}={jar[name]}" for name in names)


def _is_user_id_token(token: str | None) -> bool:
    """uid 为正数才是登录票。风控页下发的 xq_id_token 里 uid 为 -1。"""
    if not token or token.count(".") < 2:
        return False
    segment = token.split(".")[1]
    segment += "=" * (-len(segment) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(segment))
    except (json.JSONDecodeError, ValueError, TypeError):
        return False
    uid = payload.get("uid") if isinstance(payload, dict) else None
    return isinstance(uid, int) and not isinstance(uid, bool) and uid > 0


def _chrome_expiry(expires_utc: int) -> float:
    if not expires_utc:
        return float("inf")
    return expires_utc / 1_000_000 - 11644473600


def decrypt_chrome_cookie(host: str, encrypted: bytes) -> str | None:
    """解密本机 Chrome v10 Cookie。新版明文前面有 host 的 SHA256。"""
    if not encrypted or not encrypted.startswith(b"v10"):
        return None
    key = hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, dklen=16)
    try:
        plain = subprocess.run(
            ["openssl", "enc", "-d", "-aes-128-cbc", "-K", key.hex(), "-iv", (b" " * 16).hex(), "-nopad"],
            input=encrypted[3:],
            capture_output=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    pad = plain[-1] if plain else 0
    if not isinstance(pad, int) or not 1 <= pad <= 16 or plain[-pad:] != bytes([pad]) * pad:
        return None
    plain = plain[:-pad]
    prefix = hashlib.sha256(host.encode()).digest()
    if plain.startswith(prefix):
        plain = plain[len(prefix):]
    try:
        return plain.decode()
    except UnicodeDecodeError:
        return None


def profile_cookie_header(profile_dir: Path) -> str | None:
    """从已保存的 Chrome 配置读取登录 Cookie，不打开浏览器。"""
    database = profile_dir / "Default" / "Cookies"
    if not database.exists():
        return None
    uri = f"file:{database}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
    except sqlite3.Error:
        return None
    try:
        rows = connection.execute(
            "select host_key, name, value, encrypted_value, expires_utc "
            "from cookies where host_key like '%xueqiu.com'"
        ).fetchall()
    except sqlite3.Error:
        return None
    finally:
        connection.close()
    now = time.time()
    cookies: list[dict] = []
    for host, name, value, encrypted, expires_utc in rows:
        if _chrome_expiry(expires_utc or 0) <= now:
            continue
        text = value or decrypt_chrome_cookie(host, encrypted or b"")
        if text:
            cookies.append({"name": name, "value": text, "domain": host})
    return logged_in_cookie_header(cookies)


def _quote_env(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def upsert_env(path: Path, key: str, value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ValueError(f"{key} 含有换行，无法写入")
    rendered = f"{key}={_quote_env(value)}"
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    pattern = re.compile(rf"^{re.escape(key)}=.*$", re.MULTILINE)
    if pattern.search(text):
        text = pattern.sub(rendered, text, count=1)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += rendered + "\n"
    path.write_text(text, encoding="utf-8")


def load_env(path: Path) -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if path.exists():
        load_dotenv(path)


def credentials_from_env() -> tuple[str, str]:
    account = os.environ.get("XUEQIU_ACCOUNT", "").strip()
    password = os.environ.get("XUEQIU_PASSWORD", "").strip()
    return account, password


def _fill_password_login(page, account: str, password: str) -> None:
    page.get_by_text("账号密码登录", exact=True).click()
    account_box = page.get_by_placeholder("请输入手机号或者邮箱")
    account_box.wait_for(state="visible", timeout=10000)
    account_box.fill(account)
    page.get_by_placeholder("请输入登录密码").fill(password)
    agree = page.locator("[class*='modal__login__main'] [class*='nochecked']")
    if agree.count():
        agree.first.click()
    page.locator("[class*='modal__login__btn']").click()


def sms_challenge_visible(page) -> bool:
    """提交密码后的短信验证。隐藏的「验证码登录」标签不会算进去。"""
    for text in _SMS_MARKERS:
        try:
            locator = page.get_by_text(text, exact=False)
            if locator.count() and locator.first.is_visible():
                return True
        except Exception:
            continue
    return False


def _wait_for_login(context, page, seconds: int, abort_on_sms: bool) -> LoginResult:
    deadline = time.time() + seconds
    while time.time() < deadline:
        header = logged_in_cookie_header(context.cookies())
        if header:
            return LoginResult("ok", header)
        if abort_on_sms and sms_challenge_visible(page):
            return LoginResult("sms", message="出现短信验证")
        page.wait_for_timeout(1000)
    return LoginResult("failed", message="等待登录超时")


def acquire_cookie(*, interactive: bool = False, current: str | None = None) -> LoginResult:
    """打开本机 Chrome 取登录 Cookie。无人值守时遇到短信验证立刻放弃。"""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError:
        return LoginResult("failed", message="缺少 playwright")

    load_env(_ENV_PATH)
    account, password = credentials_from_env()
    wait_seconds = _TIMEOUT_SECONDS if interactive else _AUTO_TIMEOUT_SECONDS
    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(_PROFILE_DIR),
                channel="chrome",
                headless=False,
                viewport=None,
                args=["--no-first-run", "--no-default-browser-check"],
                ignore_default_args=["--enable-automation"],
            )
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(_LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
                header = logged_in_cookie_header(context.cookies())
                if header and (interactive or header != current):
                    return LoginResult("ok", header, "浏览器里已有登录态")
                if account and password:
                    try:
                        _fill_password_login(page, account, password)
                    except PlaywrightError as exc:
                        if interactive:
                            print(f"自动填写登录框失败，请在窗口里手动登录：{exc}")
                        else:
                            return LoginResult("failed", message=f"自动填写登录框失败：{exc}")
                elif not interactive:
                    return LoginResult("failed", message="未配置 XUEQIU_ACCOUNT / XUEQIU_PASSWORD")
                return _wait_for_login(context, page, wait_seconds, abort_on_sms=not interactive)
            finally:
                context.close()
    except PlaywrightError as exc:
        return LoginResult("failed", message=f"浏览器启动或登录等待失败：{exc}")


def main() -> int:
    try:
        import playwright  # noqa: F401
    except ImportError:
        print("缺少 playwright。请先执行：uv sync")
        return 1

    load_env(_ENV_PATH)
    account, password = credentials_from_env()
    print("将打开 Chrome。")
    if account and password:
        print("已读取 .env 中的账号密码，将自动填入并提交。")
        print("如果弹出图形验证码或短信验证，请在窗口里完成；登录成功后会自动写入 Cookie。")
    else:
        print("未配置 XUEQIU_ACCOUNT / XUEQIU_PASSWORD，请在打开的窗口里手动登录。")
    print("窗口会保持打开。请在里面完成登录，检测到真实登录后才会保存并关闭。")

    result = acquire_cookie(interactive=True)
    if result.status != "ok" or not result.cookie:
        if result.message:
            print(result.message)
        print("5 分钟内没有检测到登录。游客 Cookie 的 u 和设备号相同，不算登录。请重新运行并在窗口里完成登录。")
        return 1

    if result.message:
        print(result.message + "，直接保存 Cookie。")
    upsert_env(_ENV_PATH, "XUEQIU_COOKIE", result.cookie)
    print("已写入 .env 的 XUEQIU_COOKIE。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
