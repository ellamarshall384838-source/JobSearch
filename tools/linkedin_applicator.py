"""
LinkedIn Easy Apply automation using Playwright.
Handles form filling, resume upload, multi-step submission, and application logging.
"""
import json
import time
import datetime
import threading
import concurrent.futures
from pathlib import Path
from typing import Optional, Callable

from config import PROJECT_ROOT

APPLICATIONS_LOG = PROJECT_ROOT / "applications_log.json"
_log_lock = threading.Lock()


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

    from tools.linkedin_auth import load_cookies, is_session_valid

    if not is_session_valid():
        result["message"] = "请先在「⚙️ 设置」中登录 LinkedIn 账号。"
        return result

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[] if headless else ["--start-maximized"],
            )
            context = browser.new_context(
                viewport=None if not headless else {"width": 1280, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            load_cookies(context)
            page = context.new_page()

            # ── Navigate to job ──────────────────────────────────────────────
            page.goto(job_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Extract job metadata
            for sel in [
                ".job-details-jobs-unified-top-card__job-title h1",
                ".jobs-unified-top-card__job-title",
                "h1.t-24",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count():
                        result["job_title"] = el.inner_text().strip()
                        break
                except Exception:
                    pass

            for sel in [
                ".job-details-jobs-unified-top-card__company-name a",
                ".jobs-unified-top-card__company-name a",
                ".jobs-unified-top-card__subtitle-primary-grouping a",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count():
                        result["company"] = el.inner_text().strip()
                        break
                except Exception:
                    pass

            # ── Find Easy Apply button ───────────────────────────────────────
            easy_apply_btn = None
            for btn_sel in [
                'button.jobs-apply-button[aria-label*="Easy Apply"]',
                'button[aria-label*="Easy Apply"]',
                '.jobs-s-apply button',
                'button.jobs-apply-button',
            ]:
                try:
                    btn = page.locator(btn_sel).first
                    if btn.count() and btn.is_visible():
                        easy_apply_btn = btn
                        break
                except Exception:
                    pass

            if not easy_apply_btn:
                result["message"] = (
                    "此职位不支持 LinkedIn Easy Apply。\n"
                    "该职位可能需要跳转到公司官网申请，请点击链接手动完成。"
                )
                browser.close()
                return result

            easy_apply_btn.click()
            time.sleep(1.5)

            # ── Multi-step application loop ──────────────────────────────────
            submitted = False
            for _step in range(12):
                # Confirm modal is still open
                modal = page.locator('.jobs-easy-apply-modal, [data-test-modal-id="easy-apply-modal"]').first
                if not modal.count():
                    break

                _fill_form_page(page, resume_path, answer_gen, resume_content)
                time.sleep(0.5)

                # Check for Submit button
                submit_btn = page.locator(
                    'button[aria-label="Submit application"], '
                    'button[aria-label*="Submit"]'
                ).first
                if submit_btn.count() and submit_btn.is_visible():
                    submit_btn.click()
                    time.sleep(2)
                    submitted = True
                    break

                # Check for Review button
                review_btn = page.locator(
                    'button[aria-label="Review your application"], '
                    'button[aria-label*="Review"]'
                ).first
                if review_btn.count() and review_btn.is_visible():
                    review_btn.click()
                    time.sleep(1)
                    continue

                # Check for Next button
                next_btn = page.locator(
                    'button[aria-label="Continue to next step"], '
                    'button[aria-label*="Next"]'
                ).first
                if next_btn.count() and next_btn.is_visible():
                    next_btn.click()
                    time.sleep(1)
                    continue

                # No recognised navigation button — leave browser open for user
                result["message"] = (
                    "⚠️ 遇到无法自动处理的表单页面，浏览器窗口将保持打开。\n"
                    "请在浏览器中手动完成剩余步骤并提交申请。"
                )
                # Don't close the browser — let user finish
                return result

            if submitted:
                result["success"] = True
                job_disp = result["job_title"] or "该职位"
                comp_disp = result["company"] or "该公司"
                result["message"] = f"申请已成功提交：{job_disp} @ {comp_disp}"
            else:
                result["message"] = "申请流程已完成表单填写，但未检测到提交按钮，请在浏览器中确认。"

            browser.close()

    except Exception as e:
        result["message"] = f"申请过程中发生错误：{e}"

    return result


def apply_to_job(
    job_url: str,
    resume_path: Optional[Path],
    answer_gen: Callable,
    resume_content: str = "",
    headless: bool = False,
) -> dict:
    """
    Apply to a LinkedIn job via Easy Apply (runs in a background thread).

    Args:
        job_url:        Full LinkedIn job URL.
        resume_path:    PDF to upload as resume (None = skip upload).
        answer_gen:     Callable(questions: list[str], resume: str) -> dict[str, str].
        resume_content: Resume text passed to answer_gen.
        headless:       False = show browser window (recommended for local use).

    Returns dict with keys: success, message, job_title, company, url.
    """
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
