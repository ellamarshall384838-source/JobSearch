"""
LinkedIn authentication via Playwright browser automation.
Works in both LOCAL and CLOUD modes:
  - Local:  headless=False (visible browser), cookies saved to file + session_store
  - Cloud:  headless=True,  cookies saved to session_store only (survives refresh via ?sid=)

Two login methods:
  1. login_linkedin(email, password)  — Playwright automation
  2. import_cookies_from_json(json_str) — paste cookies exported from browser extension
"""
import json
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional

from config import PROJECT_ROOT

COOKIES_FILE = PROJECT_ROOT / "linkedin_session.json"
# Full Playwright storage state (cookies + localStorage) — more reliable than cookies only
STORAGE_STATE_FILE = PROJECT_ROOT / "linkedin_storage_state.json"
_lock = threading.Lock()


# ── Cookie persistence helpers ────────────────────────────────────────────────

def _save_cookies(cookies: list) -> None:
    """Persist cookies to session_store (all modes) and to disk (local only)."""
    try:
        from storage.session_store import save_linkedin_cookies
        save_linkedin_cookies(cookies)
    except Exception:
        pass  # session_store unavailable outside Streamlit — disk write below covers it

    from config import IS_CLOUD
    if not IS_CLOUD:
        with _lock:
            COOKIES_FILE.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
            )


def _load_raw_cookies() -> Optional[list]:
    """Return stored cookies from session_store or, as fallback, the local file."""
    try:
        from storage.session_store import get_linkedin_cookies
        cookies = get_linkedin_cookies()
        if cookies:
            return cookies
    except Exception:
        pass  # session_store unavailable outside Streamlit

    # File fallback: covers standalone scripts and post-refresh in local mode
    from config import IS_CLOUD
    if not IS_CLOUD and COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 20:
        try:
            with _lock:
                cookies = json.loads(COOKIES_FILE.read_text(encoding="utf-8"))
            try:
                from storage.session_store import save_linkedin_cookies
                save_linkedin_cookies(cookies)
            except Exception:
                pass
            return cookies
        except Exception:
            pass
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def is_session_valid() -> bool:
    """Return True if a non-expired li_at cookie is stored.

    We intentionally skip a live network check: LinkedIn's bot-detection
    returns a redirect-to-login even for valid sessions when accessed from
    plain HTTP clients, causing false negatives.  Actual invalidity surfaces
    inside Playwright when the browser tries to navigate.
    """
    import time
    cookies = _load_raw_cookies()
    if not cookies:
        return False
    now = time.time()
    for c in cookies:
        if c.get("name") == "li_at":
            exp = c.get("expires", 0)
            return exp == 0 or exp > now  # 0 = session cookie, treat as valid
    return False


def load_cookies(context) -> bool:
    """Inject stored cookies into a Playwright browser context."""
    cookies = _load_raw_cookies()
    if not cookies:
        return False
    try:
        context.add_cookies(cookies)
        return True
    except Exception:
        return False


def get_storage_state_path() -> str | None:
    """Return path to a valid Playwright storage state file, or None.

    Priority:
      1. Local file  linkedin_storage_state.json  (fastest path)
      2. session_store (cloud mode / in-memory) → writes temp file for Playwright
    """
    if STORAGE_STATE_FILE.exists():
        return str(STORAGE_STATE_FILE)
    try:
        from storage.session_store import get_linkedin_storage_state
        state_json = get_linkedin_storage_state()
        if state_json:
            import tempfile as _tf
            import os as _os
            tmp = _tf.NamedTemporaryFile(suffix=".json", delete=False,
                                         mode="w", encoding="utf-8")
            tmp.write(state_json)
            tmp.close()
            return tmp.name
    except Exception:
        pass
    return None


def _save_storage_state(context) -> None:
    """Persist the full Playwright storage state (cookies + localStorage) everywhere."""
    try:
        import json as _json
        state = context.storage_state()
        state_json = _json.dumps(state, ensure_ascii=False)
        # Disk (local mode)
        from config import IS_CLOUD
        if not IS_CLOUD:
            with _lock:
                STORAGE_STATE_FILE.write_text(state_json, encoding="utf-8")
        # Session store (all modes including cloud)
        try:
            from storage.session_store import save_linkedin_storage_state
            save_linkedin_storage_state(state_json)
        except Exception:
            pass
    except Exception:
        pass


def logout_linkedin() -> None:
    """Clear all stored LinkedIn session data."""
    from storage.session_store import clear_linkedin_cookies
    clear_linkedin_cookies()
    with _lock:
        if COOKIES_FILE.exists():
            COOKIES_FILE.unlink()


def get_logged_in_email() -> str:
    """Return the LinkedIn email from settings if a session is active."""
    if not is_session_valid():
        return ""
    try:
        from storage.session_store import get_settings
        return get_settings().get("linkedin_email", "")
    except Exception:
        return ""


# ── Method 1: Email + password via Playwright ─────────────────────────────────

def login_linkedin(email: str, password: str) -> tuple[bool, str]:
    """
    Log in to LinkedIn using Playwright.
    - Local: opens a visible browser (user can handle 2FA / CAPTCHA).
    - Cloud: runs headless; if LinkedIn requires verification, returns an error
             suggesting the user use the cookie-import method instead.
    """
    from config import IS_CLOUD
    headless = IS_CLOUD  # headless on cloud, visible locally

    def _do_login():
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            return False, "未安装 playwright，请运行：pip install playwright && playwright install chromium"

        try:
            with sync_playwright() as p:
                launch_args = [] if headless else ["--start-maximized"]
                browser = p.chromium.launch(
                    headless=headless,
                    args=launch_args,
                )
                context = browser.new_context(
                    viewport={"width": 1280, "height": 900} if headless else None,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                )
                page = context.new_page()
                page.goto("https://www.linkedin.com/login",
                          wait_until="domcontentloaded", timeout=30000)
                page.fill("#username", email)
                page.fill("#password", password)
                page.click('[type="submit"]')

                try:
                    page.wait_for_url("**/feed/**", timeout=60000)
                except PWTimeout:
                    current = page.url
                    if "checkpoint" in current or "challenge" in current:
                        if headless:
                            # Can't show browser on cloud — guide user to cookie method
                            browser.close()
                            return False, (
                                "LinkedIn 需要安全验证，无法在云端自动完成。\n"
                                "请改用「Cookie 导入」方式：在本地浏览器登录 LinkedIn，"
                                "用扩展程序导出 Cookie 后粘贴到此处。"
                            )
                        # Local: wait longer for user to solve challenge manually
                        try:
                            page.wait_for_url("**/feed/**", timeout=180000)
                        except PWTimeout:
                            browser.close()
                            return False, "登录超时：安全验证未完成，请重试。"
                    elif "login" in current:
                        browser.close()
                        return False, "登录失败：邮箱或密码错误，请检查后重试。"
                    else:
                        if "linkedin.com" not in current:
                            browser.close()
                            return False, f"登录异常，当前页面：{current}"

                cookies = context.cookies()
                # Save full storage state (cookies + localStorage) for Playwright auth
                _save_storage_state(context)
                browser.close()

            _save_cookies(cookies)
            return True, "✅ LinkedIn 登录成功！会话已保存，可开始自动投递简历。"

        except Exception as e:
            return False, f"登录时发生错误：{e}"

    timeout = 90 if headless else 240
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_do_login)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            return False, "登录操作超时，请稍后重试。"


# ── Method 2: Import cookies from browser extension ───────────────────────────

def import_cookies_from_json(cookies_json: str) -> tuple[bool, str]:
    """
    Parse and store cookies exported from a browser extension
    (Cookie-Editor, EditThisCookie, etc.).

    Accepts both JSON arrays (standard) and Netscape header-format strings.
    Returns (success, message).
    """
    if not cookies_json.strip():
        return False, "请粘贴从浏览器导出的 Cookie JSON。"

    try:
        raw = json.loads(cookies_json.strip())
    except json.JSONDecodeError as e:
        return False, f"JSON 格式错误：{e}\n\n请确认使用了 Cookie-Editor 等扩展的「Export as JSON」功能。"

    if isinstance(raw, dict):
        raw = [raw]  # single cookie wrapped in object

    if not isinstance(raw, list) or not raw:
        return False, "未找到有效的 Cookie 数据，请确认导出格式正确。"

    # Normalise to Playwright cookie format
    normalised = []
    for c in raw:
        if not isinstance(c, dict):
            continue
        name  = c.get("name") or c.get("Name", "")
        value = c.get("value") or c.get("Value", "")
        if not name:
            continue

        domain = c.get("domain") or c.get("Domain", ".linkedin.com")
        # li_at and JSESSIONID must stay on .www.linkedin.com; other cookies on .linkedin.com.
        if name in ("li_at", "JSESSIONID", "bscookie", "li_rm"):
            domain = ".www.linkedin.com"
        elif not domain.startswith("."):
            domain = "." + domain

        cookie = {
            "name":     name,
            "value":    str(value),
            "domain":   domain,
            "path":     c.get("path") or c.get("Path", "/"),
            "httpOnly": bool(c.get("httpOnly") or c.get("HttpOnly", False)),
            "secure":   bool(c.get("secure")   or c.get("Secure",   False)),
        }
        # expires: float (unix timestamp) or absent
        exp = c.get("expirationDate") or c.get("expires") or c.get("Expires")
        if exp and str(exp).lstrip("-").replace(".", "").isdigit():
            cookie["expires"] = float(exp)
        same = c.get("sameSite") or c.get("SameSite", "")
        if same in ("Strict", "Lax", "None"):
            cookie["sameSite"] = same

        normalised.append(cookie)

    if not normalised:
        return False, "未能解析出任何有效 Cookie，请检查数据格式。"

    # Verify at least one LinkedIn auth cookie is present
    auth_keys = {"li_at", "JSESSIONID", "liap"}
    found_auth = any(c["name"] in auth_keys for c in normalised)
    if not found_auth:
        return False, (
            "未找到 LinkedIn 认证 Cookie（li_at / JSESSIONID）。\n"
            "请确认您导出的是 linkedin.com 的 Cookie，且当前已登录 LinkedIn。"
        )

    _save_cookies(normalised)
    count = len(normalised)
    return True, f"✅ 成功导入 {count} 个 Cookie！LinkedIn 会话已激活，可开始自动投递。"
