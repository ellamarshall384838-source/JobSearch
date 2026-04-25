"""
Center chat panel: conversation display + user input + resume source selector.

Scrolling behaviour:
  - Messages live inside a fixed-height st.container(height=N) → independent scrollbar
  - After each rerun a small JS snippet scrolls that container to its bottom.
"""
import streamlit as st
import streamlit.components.v1 as components

from storage.session_store import get_settings, save_output_file
from storage.conversation_store import ConversationStore
from tools.resume_manager import (
    detect_available_sources,
    SOURCE_LABELS,
    ResumeSource,
)
from chat_engine import process_message, check_resume_source_conflict
from ui.i18n import t

_store = ConversationStore()

_MSG_AREA_HEIGHT = 560


# ── Agent initialization ──────────────────────────────────────────────────────

def _ensure_agents() -> bool:
    if st.session_state.get("agents") is not None:
        return True

    cfg = get_settings()
    if not cfg.get("api_key"):
        return False

    try:
        import agentscope
        agentscope.init()
    except Exception:
        pass

    try:
        from agents.model_factory import create_model, get_formatter
        from agents.agent_factory  import create_agents

        model     = create_model(cfg["api_key"], cfg["base_url"], cfg["model"])
        formatter = get_formatter()
        agents    = create_agents(model, formatter)

        st.session_state.model     = model
        st.session_state.formatter = formatter
        st.session_state.agents    = agents
        return True
    except Exception as e:
        lang  = st.session_state.get("lang", "zh")
        label = "初始化 Agent 失败" if lang == "zh" else "Agent init failed"
        st.error(f"{label}：{e}")
        return False


# ── Source selector ───────────────────────────────────────────────────────────

def _source_label(source_key: str) -> str:
    lang      = st.session_state.get("lang", "zh")
    labels_en = {
        ResumeSource.INTERACTIVE:   "Chat / AI-maintained resume",
        ResumeSource.FULL_SCAN:     "Full materials scan",
        ResumeSource.SPECIFIC_FILE: "Specific file",
    }
    return (labels_en if lang == "en" else SOURCE_LABELS).get(source_key, source_key)


def _render_source_selector(conv_messages: list):
    available = detect_available_sources(conv_messages)
    if not available:
        return

    spec_label   = "Specific file" if st.session_state.get("lang") == "en" else "指定文件"
    option_keys  = available + [ResumeSource.SPECIFIC_FILE]
    option_names = [_source_label(s) for s in available] + [spec_label]

    current_key = st.session_state.get("resume_source")
    try:
        idx = option_keys.index(current_key)
    except ValueError:
        idx = 0

    col_src, col_file = st.columns([2, 2])
    with col_src:
        chosen = st.selectbox(
            t("resume_source_label"),
            range(len(option_names)),
            format_func=lambda i: option_names[i],
            index=idx,
            key="resume_source_selector",
        )
        st.session_state.resume_source = option_keys[chosen]

    with col_file:
        if st.session_state.resume_source == ResumeSource.SPECIFIC_FILE:
            from storage.session_store import get_output_files, get_materials
            all_names = list(get_output_files()) + list(get_materials())
            if all_names:
                st.session_state.specific_file = st.selectbox(
                    t("select_file_label"), all_names, key="specific_file_selector"
                )
            else:
                st.caption(t("no_files_hint"))
        else:
            st.session_state.specific_file = None


# ── Message rendering ─────────────────────────────────────────────────────────

def _render_messages(messages: list):
    for msg in messages:
        role    = msg.get("role", "user")
        content = msg.get("content", "")
        avatar  = "🧑‍💻" if role == "user" else "🤖"
        with st.chat_message(role, avatar=avatar):
            st.markdown(content)


def _scroll_to_bottom(msg_count: int):
    last = st.session_state.get("_chat_scroll_count", 0)
    if msg_count <= last:
        return
    st.session_state["_chat_scroll_count"] = msg_count
    components.html(
        """
        <script>
        setTimeout(function () {
            var doc = window.parent.document;
            doc.querySelectorAll(
                '[data-testid="stVerticalBlockBorderWrapper"]'
            ).forEach(function (el) {
                if (el.scrollHeight > el.clientHeight + 4) {
                    el.scrollTop = el.scrollHeight;
                }
            });
        }, 120);
        </script>
        """,
        height=0,
        scrolling=False,
    )


# ── Public entry point ────────────────────────────────────────────────────────

def render_chat_panel():
    conv_id   = st.session_state.get("current_conv_id")
    conv_data = st.session_state.get("current_conv_data")

    if not conv_id or not conv_data:
        st.info(t("select_chat"))
        return

    messages = conv_data.get("messages", [])

    cfg = get_settings()
    if not cfg.get("api_key"):
        st.warning(t("no_api_key"))
        with st.container(height=_MSG_AREA_HEIGHT, border=False):
            _render_messages(messages)
        return

    _render_source_selector(messages)
    st.divider()

    with st.container(height=_MSG_AREA_HEIGHT, border=False):
        _render_messages(messages)

    _scroll_to_bottom(len(messages))

    user_input = st.chat_input(t("chat_placeholder"))
    if not user_input:
        return

    if not _ensure_agents():
        st.error(t("no_api_error"))
        return

    _store.add_message(conv_id, "user", user_input)
    conv_data = _store.load_conversation(conv_id)
    messages  = conv_data.get("messages", [])

    conflict_msg = check_resume_source_conflict(
        messages, st.session_state.get("resume_source")
    )
    if conflict_msg:
        _store.add_message(conv_id, "assistant", conflict_msg)
        st.session_state.current_conv_data = _store.load_conversation(conv_id)
        st.rerun()
        return

    with st.spinner(t("thinking")):
        try:
            session_state = conv_data.get("session_state", {})
            response_text, updated_ss, generated_files = process_message(
                user_message=user_input,
                agents=st.session_state.agents,
                session_state=session_state,
                conversation_messages=messages,
                resume_source=st.session_state.get("resume_source"),
                specific_file=st.session_state.get("specific_file"),
            )
        except Exception as e:
            response_text   = f"{t('error_prefix')} {e}"
            updated_ss      = conv_data.get("session_state", {})
            generated_files = []

    # Auto-open first generated file in the preview panel
    if generated_files:
        st.session_state.preview_file = f"output::{generated_files[0]}"

    _store.add_message(conv_id, "assistant", response_text)
    _store.update_session_state(conv_id, updated_ss)
    st.session_state.current_conv_data = _store.load_conversation(conv_id)
    st.rerun()
