"""
One-time LinkedIn session setup.

Opens a browser window for you to log in to LinkedIn.
Saves the complete session state (cookies + localStorage) to
linkedin_storage_state.json so future Easy Apply operations work
without needing to re-authenticate.

Usage:
    python setup_linkedin_session.py
"""
import sys
import os
import json
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
os.chdir(str(ROOT))

STORAGE_STATE_FILE = ROOT / "linkedin_storage_state.json"

print("=== LinkedIn Session Setup ===")
print()
print("A browser window will open at the LinkedIn login page.")
print("Please log in, then wait for this script to finish automatically.")
print("(Your existing browsers are NOT affected — this is a separate window)")
print()

from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    # Use Edge if available, otherwise Chromium — but a FRESH non-persistent context
    # so storage_state() captures localStorage correctly
    try:
        browser = p.chromium.launch(
            channel="msedge",
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        print("Using Microsoft Edge")
    except Exception:
        browser = p.chromium.launch(
            headless=False,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        print("Using Chromium")

    context = browser.new_context(
        viewport={"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    page = context.new_page()
    page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
    print("\nBrowser opened. Please log in to LinkedIn.")
    print("Waiting up to 3 minutes...")

    # Wait for successful login (URL changes to /feed/)
    try:
        page.wait_for_url("**/feed/**", timeout=180000)
    except Exception:
        current = page.url
        if "login" in current or "checkpoint" in current:
            print("Login not completed within 3 minutes. Re-run the script.")
            browser.close()
            sys.exit(1)

    # Give LinkedIn a moment to fully load and set localStorage
    time.sleep(3)

    print(f"\nLogged in! Current page: {page.url[:60]}")
    print("Saving session state...")
    state = context.storage_state()
    STORAGE_STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False), encoding="utf-8"
    )
    n_cookies = len(state.get("cookies", []))
    n_ls = sum(len(o.get("localStorage", [])) for o in state.get("origins", []))
    print(f"\nOK: Session saved to linkedin_storage_state.json")
    print(f"   Cookies: {n_cookies}")
    print(f"   localStorage entries: {n_ls}")
    browser.close()

print("\nSetup complete. You can now use job search and Easy Apply features.")
