"""
Settings dialog: API configuration + LinkedIn authentication.
LinkedIn supports two login methods (both work on local and cloud):
  1. Email + password  via Playwright (headless on cloud, visible locally)
  2. Cookie import     paste JSON exported from browser (Cookie-Editor extension)
"""
import streamlit as st
from storage.session_store import get_settings, save_settings
from agents.model_factory import validate_api
from ui.i18n import t


@st.dialog("Settings / 设置", width="large")
def show_settings_dialog():
    current = get_settings()

    # ── API configuration ─────────────────────────────────────────────────────
    st.markdown(t("api_config_header"))
    st.caption(t("api_caption"))

    api_key = st.text_input(
        t("api_key_label"), value=current.get("api_key", ""),
        type="password", placeholder=t("api_key_placeholder"),
    )
    base_url = st.text_input(
        t("base_url_label"), value=current.get("base_url", ""),
        placeholder="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    model = st.text_input(
        t("model_label"), value=current.get("model", "gemini-2.5-flash"),
        placeholder="gemini-2.5-flash / gpt-4o / qwen3.5:4b",
    )

    st.divider()
    col_test, col_save, col_cancel = st.columns([1, 1, 1])

    with col_test:
        if st.button(t("test_btn"), use_container_width=True):
            if not api_key.strip():
                st.error(t("no_api_key_warn"))
            else:
                with st.spinner(t("testing")):
                    ok, msg = validate_api(api_key.strip(), base_url.strip(), model.strip())
                st.success(msg) if ok else st.error(msg)

    with col_save:
        if st.button(t("save_btn"), type="primary", use_container_width=True):
            if not api_key.strip():
                st.error(t("no_api_key_warn"))
            else:
                save_settings(api_key.strip(), base_url.strip(), model.strip(),
                              current.get("linkedin_email", ""),
                              current.get("linkedin_password", ""))
                for k in ("model", "formatter", "agents"):
                    st.session_state.pop(k, None)
                st.success(t("saved_msg"))
                st.rerun()

    with col_cancel:
        if st.button(t("cancel_btn"), use_container_width=True):
            st.rerun()

    # ── LinkedIn authentication ───────────────────────────────────────────────
    st.divider()
    st.markdown(t("linkedin_section_header"))

    from tools.linkedin_auth import is_session_valid, logout_linkedin, get_logged_in_email
    from config import IS_CLOUD

    # Status banner
    if is_session_valid():
        email_disp = get_logged_in_email() or t("linkedin_unknown_email")
        st.success(f"✅ {t('linkedin_logged_in')}: **{email_disp}**")
        if st.button(t("linkedin_logout_btn"), use_container_width=False):
            logout_linkedin()
            st.info(t("linkedin_logged_out"))
            st.rerun()
    else:
        st.warning(f"⚠️ {t('linkedin_not_logged_in')}")

    st.caption(t("linkedin_section_caption"))

    # Two login method tabs
    tab_pwd, tab_cookie = st.tabs(["🔑 账号密码登录", "🍪 Cookie 导入（推荐）"])

    # ── Tab 1: Email + password ───────────────────────────────────────────────
    with tab_pwd:
        if IS_CLOUD:
            st.info(
                "☁️ 云端模式：账号密码登录使用无头浏览器。若 LinkedIn 触发安全验证，"
                "请改用右侧「Cookie 导入」方式（更稳定）。"
            )
        else:
            st.caption("本地模式：将弹出可见浏览器窗口，如遇 2FA 可手动完成。")

        li_email = st.text_input(
            t("linkedin_email_label"),
            value=current.get("linkedin_email", ""),
            placeholder="your@email.com",
            key="li_email",
        )
        li_password = st.text_input(
            t("linkedin_password_label"),
            value=current.get("linkedin_password", ""),
            type="password",
            placeholder="LinkedIn 密码",
            key="li_pass",
        )

        if st.button(t("linkedin_login_btn"), type="primary", use_container_width=True):
            if not li_email.strip() or not li_password.strip():
                st.error(t("linkedin_no_creds"))
            else:
                save_settings(api_key.strip(), base_url.strip(), model.strip(),
                              li_email.strip(), li_password.strip())
                if IS_CLOUD:
                    st.info("正在使用无头浏览器登录（约 30-60 秒）…")
                else:
                    st.info(t("linkedin_browser_opening"))
                with st.spinner(t("linkedin_logging_in")):
                    from tools.linkedin_auth import login_linkedin
                    ok, msg = login_linkedin(li_email.strip(), li_password.strip())
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

    # ── Tab 2: Cookie import ──────────────────────────────────────────────────
    with tab_cookie:
        st.markdown("""
**推荐方式 · 3 步完成，无需密码**

1. 在浏览器安装扩展 **[Cookie-Editor](https://cookie-editor.com/)**（Chrome / Firefox 均支持）
2. 打开 [linkedin.com](https://www.linkedin.com)，确认已登录
3. 点击扩展图标 → 点击右上角「导出」按钮（Export） → 复制全部 JSON
4. 粘贴到下方文本框，点击「导入」
""")

        cookie_json = st.text_area(
            "粘贴 Cookie JSON",
            height=160,
            placeholder='[{"name":"li_at","value":"AQED...","domain":".linkedin.com",...},...]',
            key="cookie_import_input",
        )

        if st.button("📥 导入 Cookie", type="primary", use_container_width=True):
            if not cookie_json.strip():
                st.error("请先粘贴从浏览器导出的 Cookie JSON。")
            else:
                from tools.linkedin_auth import import_cookies_from_json
                ok, msg = import_cookies_from_json(cookie_json.strip())
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

    st.caption(t("linkedin_tos_note"))
