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
    tab_pwd, tab_cookie = st.tabs([t("linkedin_tab_password"), t("linkedin_tab_cookie")])

    # ── Tab 1: Email + password ───────────────────────────────────────────────
    with tab_pwd:
        if IS_CLOUD:
            st.info(t("linkedin_cloud_hint"))
        else:
            st.caption(t("linkedin_local_hint"))

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
            placeholder=t("linkedin_password_ph"),
            key="li_pass",
        )

        if st.button(t("linkedin_login_btn"), type="primary", use_container_width=True):
            if not li_email.strip() or not li_password.strip():
                st.error(t("linkedin_no_creds"))
            else:
                save_settings(api_key.strip(), base_url.strip(), model.strip(),
                              li_email.strip(), li_password.strip())
                st.info(t("linkedin_headless_login") if IS_CLOUD else t("linkedin_browser_opening"))
                with st.spinner(t("linkedin_logging_in")):
                    from tools.linkedin_auth import login_linkedin
                    ok, msg = login_linkedin(li_email.strip(), li_password.strip())
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

    # ── Tab 2: Cookie import ──────────────────────────────────────────────────
    with tab_cookie:
        st.markdown(t("linkedin_cookie_title") + "\n\n" + t("linkedin_cookie_steps"))

        cookie_json = st.text_area(
            t("linkedin_cookie_label"),
            height=160,
            placeholder='[{"name":"li_at","value":"AQED...","domain":".linkedin.com",...},...]',
            key="cookie_import_input",
        )

        if st.button(t("linkedin_cookie_import"), type="primary", use_container_width=True):
            if not cookie_json.strip():
                st.error(t("linkedin_cookie_empty"))
            else:
                from tools.linkedin_auth import import_cookies_from_json
                ok, msg = import_cookies_from_json(cookie_json.strip())
                st.success(msg) if ok else st.error(msg)
                if ok:
                    st.rerun()

    st.caption(t("linkedin_tos_note"))
