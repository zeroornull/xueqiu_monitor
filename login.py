"""用 .env 里的账号密码登录雪球，并把 Cookie 写回 .env。"""

import os
import re
import sys
import time
from pathlib import Path

_ENV_PATH = Path(__file__).resolve().parent / ".env"
_PROFILE_DIR = Path(__file__).resolve().parent / ".xueqiu-chrome"
_LOGIN_URL = "https://xueqiu.com/"
_TIMEOUT_SECONDS = 300
_PREFERRED = ("xq_a_token", "u", "xq_r_token", "xq_id_token")


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
    names = [name for name in _PREFERRED if name in jar]
    names.extend(name for name in jar if name not in names)
    return ";".join(f"{name}={jar[name]}" for name in names)


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


def _wait_for_login(context, page) -> str | None:
    deadline = time.time() + _TIMEOUT_SECONDS
    while time.time() < deadline:
        header = logged_in_cookie_header(context.cookies())
        if header:
            return header
        page.wait_for_timeout(1000)
    return None


def main() -> int:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
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

    header = None
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
                if header:
                    print("浏览器里已有登录态，直接保存 Cookie。")
                elif account and password:
                    try:
                        _fill_password_login(page, account, password)
                    except PlaywrightError as exc:
                        print(f"自动填写登录框失败，请在窗口里手动登录：{exc}")
                if not header:
                    print("窗口会保持打开。请在里面完成登录，检测到真实登录后才会保存并关闭。")
                    header = _wait_for_login(context, page)
            finally:
                context.close()
    except PlaywrightError as exc:
        print(f"浏览器启动或登录等待失败：{exc}")
        return 1

    if not header:
        print("5 分钟内没有检测到登录。游客 Cookie 的 u 和设备号相同，不算登录。请重新运行并在窗口里完成登录。")
        return 1

    upsert_env(_ENV_PATH, "XUEQIU_COOKIE", header)
    print("已写入 .env 的 XUEQIU_COOKIE。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
