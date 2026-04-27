"""
LinkedIn Easy Apply automation using Playwright.
Handles form filling, resume upload, multi-step submission, and application logging.
"""
import json
import re
import time
import datetime
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional, Callable

from config import PROJECT_ROOT

APPLICATIONS_LOG = PROJECT_ROOT / "applications_log.json"
_log_lock = threading.Lock()

def _has_easy_apply(page) -> bool:
    """
    Detect Easy Apply button using text content (robust against LinkedIn's CSS obfuscation).
    LinkedIn frequently changes class names; button text is stable.
    Returns True if an Easy Apply / 快速申请 button is present on the page.
    """
    try:
        # Primary: look for button with exact Easy Apply text (Chinese or English)
        if page.get_by_text("快速申请", exact=True).count() > 0:
            return True
        if page.get_by_text("Easy Apply", exact=True).count() > 0:
            return True
        # Fallback: aria-label based (old LinkedIn UI compatibility)
        if page.locator('button[aria-label*="Easy Apply"]').count() > 0:
            return True
        if page.locator('button[aria-label*="快速申请"]').count() > 0:
            return True
        # Fallback: jobs-apply-button class (old UI)
        ea = page.locator("button.jobs-apply-button")
        if ea.count() > 0 and ea.first.is_visible():
            return True
    except Exception:
        pass
    return False


def _normalize_linkedin_url(url: str) -> str:
    """Convert currentJobId= or country-subdomain URLs to www.linkedin.com/jobs/view/."""
    cjid = re.search(r"currentJobId=(\d+)", url)
    if cjid:
        return f"https://www.linkedin.com/jobs/view/{cjid.group(1)}/"
    return re.sub(
        r"https?://(?!www\.)[a-z]{2}\.linkedin\.com/",
        "https://www.linkedin.com/",
        url,
    )


def _make_browser_context(p, headless: bool):
    """Create a Playwright browser + context, using storage state if available."""
    from tools.linkedin_auth import get_storage_state_path, load_cookies

    browser = p.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"]
              + ([] if headless else ["--start-maximized"]),
    )
    state_path = get_storage_state_path()
    kwargs = dict(
        viewport=None if not headless else {"width": 1280, "height": 900},
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
    )
    if state_path:
        kwargs["storage_state"] = state_path
        print("[Applicator] Auth: storage_state")
    context = browser.new_context(**kwargs)
    if not state_path:
        load_cookies(context)
        print("[Applicator] Auth: cookie injection")
    return browser, context


# ── Batch Easy Apply pre-filter ───────────────────────────────────────────────

def filter_easy_apply_urls(urls: list[str], headless: bool = None) -> list[str]:
    """
    Given a list of LinkedIn job URLs, return only those that have an Easy Apply button.
    Uses 2 parallel browser instances for ~2x speed vs sequential.
    No LLM needed — pure text detection ("快速申请" / "Easy Apply").
    """
    if not urls:
        return []

    if headless is None:
        from config import IS_CLOUD
        headless = IS_CLOUD

    # Deduplicate and normalise
    seen: set = set()
    deduped = []
    for u in urls:
        n = _normalize_linkedin_url(u)
        if n not in seen:
            seen.add(n)
            deduped.append(u)

    def _check_batch(batch: list[str]) -> list[str]:
        """Check a batch of URLs in a single browser instance."""
        from playwright.sync_api import sync_playwright
        easy: list[str] = []
        with sync_playwright() as p:
            browser, context = _make_browser_context(p, headless)
            # Warm up: visit feed so LinkedIn SPA initialises
            try:
                warmup = context.new_page()
                warmup.goto("https://www.linkedin.com/feed/",
                            wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                warmup.close()
            except Exception:
                pass

            for url in batch:
                nav_url = _normalize_linkedin_url(url)
                page = None
                try:
                    page = context.new_page()
                    page.goto(nav_url, wait_until="domcontentloaded", timeout=20000)
                    # Wait for React to render (up to 5 s)
                    for _ in range(5):
                        if page.locator("button").count() >= 10:
                            break
                        time.sleep(1)
                    page.evaluate("window.scrollTo(0, 300)")
                    time.sleep(0.5)
                    found = _has_easy_apply(page)
                    status = "[Easy Apply]" if found else "[external  ]"
                    print(f"  [Filter] {status}: {nav_url[-65:]}")
                    if found:
                        easy.append(url)
                except Exception as e:
                    print(f"  [Filter] skip {nav_url[-50:]}: {type(e).__name__}")
                finally:
                    try:
                        if page:
                            page.close()
                    except Exception:
                        pass
                time.sleep(0.5)
            browser.close()
        return easy

    # Split into 2 halves and run in parallel for ~2x throughput
    mid = max(1, len(deduped) // 2)
    batch1 = deduped[:mid]
    batch2 = deduped[mid:]

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(_check_batch, batch1)
            f2 = executor.submit(_check_batch, batch2) if batch2 else None
            result1 = f1.result(timeout=300)
            result2 = f2.result(timeout=300) if f2 else []
            # Preserve original order
            ea_set = set(_normalize_linkedin_url(u) for u in result1 + result2)
            return [u for u in deduped if _normalize_linkedin_url(u) in ea_set]
    except concurrent.futures.TimeoutError:
        print("[Applicator] Easy Apply filter timed out")
        return []


# ── Application log ───────────────────────────────────────────────────────────

def load_applications_log() -> list:
    """Return list of past application records."""
    if APPLICATIONS_LOG.exists():
        try:
            with _log_lock:
                return json.loads(APPLICATIONS_LOG.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _append_application(record: dict) -> None:
    with _log_lock:
        log = []
        if APPLICATIONS_LOG.exists():
            try:
                log = json.loads(APPLICATIONS_LOG.read_text(encoding="utf-8"))
            except Exception:
                pass
        log.append(record)
        APPLICATIONS_LOG.write_text(
            json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ── Form page filler ──────────────────────────────────────────────────────────

def _get_label_for(page, element) -> str:
    """Best-effort: return visible label text associated with a form element."""
    try:
        el_id = element.get_attribute("id")
        if el_id:
            lbl = page.locator(f'label[for="{el_id}"]').first
            if lbl.count():
                return lbl.inner_text().strip()
        aria = element.get_attribute("aria-label") or ""
        if aria:
            return aria.strip()
        placeholder = element.get_attribute("placeholder") or ""
        return placeholder.strip()
    except Exception:
        return ""


def _fill_form_page(page, resume_path: Optional[Path], answer_gen: Callable, resume_content: str) -> None:
    """
    Fill all visible form fields on the current Easy Apply step.
    - Uploads resume to any file input.
    - Asks the AI to answer text/select questions it hasn't seen values for.
    """
    # File upload
    for file_input in page.locator('input[type="file"]').all():
        if resume_path and resume_path.exists():
            try:
                file_input.set_input_files(str(resume_path))
                time.sleep(0.5)
            except Exception:
                pass

    # Collect unfilled text / textarea inputs
    pending_text: list[tuple] = []  # (element, label)
    for inp in page.locator('input[type="text"]:visible, input[type="tel"]:visible, input[type="email"]:visible, textarea:visible').all():
        try:
            if inp.input_value().strip():
                continue  # already filled
            label = _get_label_for(page, inp)
            pending_text.append((inp, label))
        except Exception:
            pass

    # Collect unfilled selects
    pending_select: list[tuple] = []  # (element, label, [options])
    for sel in page.locator('select:visible').all():
        try:
            label = _get_label_for(page, sel)
            opts = [
                o.inner_text().strip()
                for o in sel.locator("option").all()
                if o.inner_text().strip() not in ("", "Select an option", "请选择", "-- Select --")
            ]
            pending_select.append((sel, label, opts))
        except Exception:
            pass

    # Ask AI for answers if anything is pending
    questions = []
    for _, lbl in pending_text:
        questions.append(lbl or "Text field")
    for _, lbl, opts in pending_select:
        questions.append(f"{lbl or 'Select'} (选项: {', '.join(opts[:6])})")

    answers: dict = {}
    if questions:
        try:
            answers = answer_gen(questions, resume_content) or {}
        except Exception:
            answers = {}

    # Fill text inputs
    q_idx = 0
    for inp, lbl in pending_text:
        answer = answers.get(lbl) or answers.get(questions[q_idx] if q_idx < len(questions) else "") or ""
        q_idx += 1
        if answer:
            try:
                inp.clear()
                inp.fill(str(answer))
            except Exception:
                pass

    # Fill selects
    for sel, lbl, opts in pending_select:
        answer = answers.get(lbl) or answers.get(questions[q_idx] if q_idx < len(questions) else "") or ""
        q_idx += 1
        if answer and opts:
            try:
                # Try exact match first, then first option as fallback
                if answer in opts:
                    sel.select_option(label=answer)
                else:
                    sel.select_option(index=1)
            except Exception:
                pass

    # Handle radio buttons (select first visible option if none selected)
    for radio_group in page.locator('.fb-radio-group:visible, [role="radiogroup"]:visible').all():
        try:
            radios = radio_group.locator('input[type="radio"]').all()
            if radios and not any(r.is_checked() for r in radios):
                radios[0].check()
        except Exception:
            pass


# ── Easy Apply orchestrator ───────────────────────────────────────────────────

def _run_easy_apply(
    job_url: str,
    resume_path: Optional[Path],
    answer_gen: Callable,
    resume_content: str,
    headless: bool,
) -> dict:
    result = {
        "success": False,
        "message": "",
        "job_title": "",
        "company": "",
        "url": job_url,
    }

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        result["message"] = "未安装 playwright，请运行：pip install playwright && playwright install chromium"
        return result

    from tools.linkedin_auth import load_cookies

    try:
        with sync_playwright() as p:
            browser, context = _make_browser_context(p, headless)
            page = context.new_page()

            # Warm up SPA: navigate to feed so React initialises properly
            try:
                page.goto("https://www.linkedin.com/feed/",
                          wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
            except Exception:
                pass

            # ── Navigate to job ──────────────────────────────────────────────
            nav_url = _normalize_linkedin_url(job_url)
            page.goto(nav_url, wait_until="domcontentloaded", timeout=30000)
            # Wait for React to render the job content
            for _ in range(8):
                if page.locator("button").count() >= 10:
                    break
                time.sleep(1)

            # ── Extract job metadata ─────────────────────────────────────────
            # Use page text extraction — more robust than class-based selectors
            try:
                meta = page.evaluate("""() => {
                    const h1 = document.querySelector('h1');
                    const title = h1 ? h1.textContent.trim() : '';
                    // Company: find the first link inside the top-card area near h1
                    const companyEl = document.querySelector(
                        '[class*="topcard"] a, [class*="top-card"] a, ' +
                        '[class*="company"] a, [data-test-id="top-card"] a'
                    );
                    const company = companyEl ? companyEl.textContent.trim() : '';
                    return {title, company};
                }""")
                if meta["title"] and meta["title"].lower() not in ("join linkedin", "linkedin"):
                    result["job_title"] = meta["title"]
                if meta["company"]:
                    result["company"] = meta["company"]
            except Exception:
                pass

            # Scroll to trigger lazy-loaded content
            try:
                page.evaluate("window.scrollTo(0, 300)")
                time.sleep(1)
            except Exception:
                pass

            # ── Find Easy Apply button ───────────────────────────────────────
            # Use text-based detection (robust against LinkedIn's CSS obfuscation)
            easy_apply_btn = None
            for locator_fn in [
                lambda: page.get_by_text("快速申请", exact=True),
                lambda: page.get_by_text("Easy Apply", exact=True),
                lambda: page.locator('button[aria-label*="Easy Apply"]'),
                lambda: page.locator('button[aria-label*="快速申请"]'),
                lambda: page.locator("button.jobs-apply-button"),
            ]:
                try:
                    loc = locator_fn()
                    if loc.count() > 0 and loc.first.is_visible():
                        easy_apply_btn = loc.first
                        break
                except Exception:
                    pass

            def _close():
                try:
                    browser.close()
                except Exception:
                    pass

            if not easy_apply_btn:
                result["message"] = (
                    "此职位不支持 LinkedIn Easy Apply。\n"
                    "该职位可能需要跳转到公司官网申请，请点击链接手动完成。"
                )
                _close()
                return result

            easy_apply_btn.click()
            time.sleep(2)

            # ── Multi-step application loop ──────────────────────────────────
            submitted = False
            for _step in range(12):
                time.sleep(1.5)

                # Fill visible form fields on this step
                try:
                    _fill_form_page(page, resume_path, answer_gen, resume_content)
                except Exception:
                    pass
                time.sleep(1)

                # Find primary navigation button inside the modal.
                # Strategy: look in dialog/modal first, then whole page.
                # LinkedIn uses text like "下一步", "提交申请", "检查你的申请".
                nav_btn = None
                submit_found = False

                try:
                    nav_candidates = page.evaluate("""() => {
                        const container = document.querySelector(
                            'dialog[open], [role=\"dialog\"], .jobs-easy-apply-modal, [data-test-modal-id]'
                        ) || document.body;
                        return Array.from(container.querySelectorAll('button'))
                            .filter(b => !b.disabled && b.offsetParent !== null)
                            .map(b => ({
                                text: b.textContent.trim(),
                                label: b.getAttribute('aria-label') || '',
                            }))
                            .filter(b => b.text || b.label);
                    }""")
                except Exception as nav_e:
                    # "Execution context was destroyed" means a navigation happened
                    # (form submitted and redirected) — treat as likely success
                    if "context" in str(nav_e).lower() or "navigation" in str(nav_e).lower():
                        submitted = True
                    break
                print(f"  [Step {_step}] Modal buttons: {[b['text'][:20] for b in nav_candidates]}")

                # Identify button type by text
                for btn_info in nav_candidates:
                    t = btn_info["text"].lower()
                    l = btn_info["label"].lower()
                    combined = t + " " + l
                    if any(k in combined for k in ["提交", "submit"]):
                        try:
                            nav_btn = page.get_by_text(btn_info["text"], exact=True).first
                            if not nav_btn.count():
                                nav_btn = page.locator(f'button[aria-label*="{btn_info["label"]}"]').first
                            submit_found = True
                            break
                        except Exception:
                            pass
                    elif any(k in combined for k in ["检查", "review"]):
                        try:
                            nav_btn = page.get_by_text(btn_info["text"], exact=True).first
                            break
                        except Exception:
                            pass
                    elif any(k in combined for k in ["下一步", "next", "continue", "继续"]):
                        try:
                            nav_btn = page.get_by_text(btn_info["text"], exact=True).first
                            break
                        except Exception:
                            pass

                # Fallback: use the last primary/prominent button in the modal
                if nav_btn is None and nav_candidates:
                    last = nav_candidates[-1]
                    try:
                        nav_btn = page.get_by_text(last["text"], exact=True).first
                    except Exception:
                        pass

                if nav_btn is None:
                    result["message"] = (
                        "遇到无法识别导航按钮的表单页面，浏览器窗口将保持打开。\n"
                        "请在浏览器中手动完成剩余步骤并提交申请。"
                    )
                    return result

                try:
                    nav_btn.click()
                except Exception as e:
                    result["message"] = f"点击按钮失败：{e}"
                    return result

                if submit_found:
                    time.sleep(2)
                    submitted = True
                    break
                time.sleep(1)

            if submitted:
                result["success"] = True
                job_disp = result["job_title"] or "该职位"
                comp_disp = result["company"] or "该公司"
                result["message"] = f"申请已成功提交：{job_disp} @ {comp_disp}"
            else:
                result["message"] = "申请流程已完成表单填写，但未检测到提交按钮，请在浏览器中确认。"

            _close()

    except Exception as e:
        result["message"] = f"申请过程中发生错误：{e}"

    return result


def apply_to_job(
    job_url: str,
    resume_path: Optional[Path],
    answer_gen: Callable,
    resume_content: str = "",
    headless: bool = None,  # None = auto (True on cloud, False locally)
) -> dict:
    """
    Apply to a LinkedIn job via Easy Apply (runs in a background thread).
    headless=None auto-selects: True on cloud, False locally (shows browser).
    Returns dict with keys: success, message, job_title, company, url.
    """
    if headless is None:
        from config import IS_CLOUD
        headless = IS_CLOUD
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _run_easy_apply, job_url, resume_path, answer_gen, resume_content, headless
        )
        try:
            result = future.result(timeout=180)
        except concurrent.futures.TimeoutError:
            result = {
                "success": False,
                "message": "申请操作超时（3分钟）。请检查浏览器是否有未处理的验证步骤。",
                "job_title": "",
                "company": "",
                "url": job_url,
            }

    # Log every attempt
    _append_application({
        **result,
        "timestamp": datetime.datetime.now().isoformat(),
    })
    return result
