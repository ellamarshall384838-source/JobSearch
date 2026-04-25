"""
LinkedIn authentication via Playwright browser automation.
Manages login, session cookies, and logout.
"""
import json
import threading
import concurrent.futures
from pathlib import Path

from config import PROJECT_ROOT

COOKIES_FILE = PROJECT_ROOT / "linkedin_session.json"
_lock = threading.Lock()


def is_session_valid() -> bool:
    """Return True if a valid LinkedIn session exists (local cookie file)."""
    from config import IS_CLOUD
    if IS_CLOUD:
        return False  # browser automation not available on cloud
    return COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 20


def login_linkedin(email: str, password: str) -> tuple[bool, str]:
    """
    Open a visible browser, log in to LinkedIn, save session cookies.
    The browser is shown so the user can handle 2FA / CAPTCHA if needed.
    Only available in local (non-cloud) mode.
    """
    from config import IS_CLOUD
    if IS_CLOUD:
        return False, "云端部署模式不支持 LinkedIn 自动登录。"

    def _do_login():
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            return False, "未安装 playwright，请运行：pip install playwright && playwright install chromium"

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=False,
                    args=["--start-maximized"],
                )
                context = browser.new_context(
                    viewport=None,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded", timeout=30000)
                page.fill("#username", email)
                page.fill("#password", password)
                page.click('[type="submit"]')

                # Wait for successful login (feed page) with extended timeout for 2FA
                try:
                    page.wait_for_url("**/feed/**", timeout=90000)
                except PWTimeout:
                    current = page.url
                    if "checkpoint" in current or "challenge" in current:
                        # Stay open; user must solve security challenge manually
                        # Wait again after user interaction
                        try:
                            page.wait_for_url("**/feed/**", timeout=120000)
                        except PWTimeout:
                            browser.close()
                            return False, "登录超时：LinkedIn 安全验证未完成，请重试。"
                    elif "login" in current:
                        browser.close()
                        return False, "登录失败：邮箱或密码错误，请检查后重试。"
                    else:
                        # May already be on feed with different URL pattern
                        if "linkedin.com" not in current:
                            browser.close()
                            return False, f"登录异常，当前页面：{current}"

                # Save cookies
                cookies = context.cookies()
                with _lock:
                    COOKIES_FILE.write_text(
                        json.dumps(cookies, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                browser.close()
                return True, "✅ LinkedIn 登录成功！会话已保存，可开始自动投递简历。"

        except Exception as e:
            return False, f"登录时发生错误：{e}"

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_login)
        try:
            return future.result(timeout=240)
        except concurrent.futures.TimeoutError:
            return False, "登录操作超时（4分钟）。请关闭浏览器窗口后重试。"


def load_cookies(context) -> bool:
    """Inject saved cookies into a Playwright browser context. Returns True on success."""
    if not COOKIES_FILE.exists():
        return False
    try:
        with _lock:
            cookies = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
        context.add_cookies(cookies)
        return True
    except Exception:
        return False


def logout_linkedin() -> None:
    """Delete saved session so the user is effectively logged out."""
    with _lock:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()


def get_logged_in_email() -> str:
    """Return the LinkedIn email from session settings if logged in, else empty string."""
    if not is_session_valid():
        return ""
    try:
        from storage.session_store import get_settings
        return get_settings().get("linkedin_email", "")
    except Exception:
        return ""
