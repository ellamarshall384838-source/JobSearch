"""
Settings dialog: API key, Base URL, model name, and LinkedIn account configuration.
Settings are stored in st.session_state (per-user, never on disk).
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
        t("api_key_label"),
        value=current.get("api_key", ""),
        type="password",
        placeholder=t("api_key_placeholder"),
    )
    base_url = st.text_input(
        t("base_url_label"),
        value=current.get("base_url", ""),
        placeholder="https://generativelanguage.googleapis.com/v1beta/openai/",
    )
    model = st.text_input(
        t("model_label"),
        value=current.get("model", "gemini-2.5-flash"),
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
                if ok:
                    st.success(msg)
                else:
                    st.error(msg)

    with col_save:
        if st.button(t("save_btn"), type="primary", use_container_width=True):
            if not api_key.strip():
                st.error(t("no_api_key_warn"))
            else:
                save_settings(
                    api_key.strip(), base_url.strip(), model.strip(),
                    current.get("linkedin_email", ""),
                    current.get("linkedin_password", ""),
                )
                for key in ("model", "formatter", "agents"):
                    st.session_state.pop(key, None)
                st.success(t("saved_msg"))
                st.rerun()

    with col_cancel:
        if st.button(t("cancel_btn"), use_container_width=True):
            st.rerun()

    # ── LinkedIn account (local mode only) ────────────────────────────────────
    from config import IS_CLOUD
    st.divider()
    st.markdown(t("linkedin_section_header"))
    st.caption(t("linkedin_section_caption"))

    if IS_CLOUD:
        st.info("☁️ 云端部署模式：LinkedIn 自动投递功能仅在本地运行时可用。")
        return

    from tools.linkedin_auth import is_session_valid, logout_linkedin

    if is_session_valid():
        email_display = current.get("linkedin_email") or t("linkedin_unknown_email")
        st.success(f"✅ {t('linkedin_logged_in')}: **{email_display}**")
    else:
        st.warning(f"⚠️ {t('linkedin_not_logged_in')}")

    linkedin_email = st.text_input(
        t("linkedin_email_label"),
        value=current.get("linkedin_email", ""),
        placeholder="your@email.com",
        key="li_email_input",
    )
    linkedin_password = st.text_input(
        t("linkedin_password_label"),
        value=current.get("linkedin_password", ""),
        type="password",
        placeholder="LinkedIn 密码",
        key="li_pass_input",
    )

    col_login, col_logout = st.columns([2, 1])

    with col_login:
        if st.button(t("linkedin_login_btn"), type="primary", use_container_width=True):
            if not linkedin_email.strip() or not linkedin_password.strip():
                st.error(t("linkedin_no_creds"))
            else:
                save_settings(
                    api_key.strip(), base_url.strip(), model.strip(),
                    linkedin_email.strip(), linkedin_password.strip(),
                )
                st.info(t("linkedin_browser_opening"))
                with st.spinner(t("linkedin_logging_in")):
                    from tools.linkedin_auth import login_linkedin
                    ok, msg = login_linkedin(linkedin_email.strip(), linkedin_password.strip())
                if ok:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)

    with col_logout:
        if st.button(t("linkedin_logout_btn"), use_container_width=True,
                     disabled=not is_session_valid()):
            logout_linkedin()
            st.info(t("linkedin_logged_out"))
            st.rerun()

    st.caption(t("linkedin_tos_note"))
