"""
app.py – Streamlit entry point for the AI 就业简历助手 / AI Job Search Assistant.

Layout (3 vertical columns):
  ┌──────────────┬────────────────────┬──────────────────┐
  │  Left panel  │   Chat (center)    │  Preview (right) │
  │  [对话][文件] │  Conversation UI   │  File renderer   │
  │  [材料库]    │                    │                  │
  └──────────────┴────────────────────┴──────────────────┘
"""
import os
import json
import streamlit as st

# ── Page config (MUST be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="AI Job Search Assistant",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Imports (after page config) ───────────────────────────────────────────────
from storage.conversation_store import ConversationStore
from storage.session_store import get_settings, save_settings
from ui.left_panel      import render_left_panel
from ui.chat_panel      import render_chat_panel
from ui.preview_panel   import render_preview_panel
from ui.settings_dialog import show_settings_dialog
from ui.i18n            import t

# ── Global CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    header[data-testid="stHeader"] {
        height: 0 !important;
        min-height: 0 !important;
        visibility: hidden;
    }
    .block-container {
        padding-top: 0.75rem !important;
        padding-bottom: 0 !important;
    }
    /* ── VSCode / ChatGPT style file & conversation buttons ── */
    div[data-testid="column"] .stButton > button {
        text-align: left !important;
        justify-content: flex-start !important;
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        display: block !important;
        padding-left: 6px !important;
        font-size: 0.85rem !important;
        line-height: 1.4 !important;
    }
    /* Keep icon tight to text */
    div[data-testid="column"] .stButton > button p {
        white-space: nowrap !important;
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        margin: 0 !important;
    }
    div[data-testid="stChatInput"] { position: sticky; bottom: 0; }
    hr { margin: 0.3rem 0; }
    /* Remove border from scrollable panels so they blend in */
    [data-testid="stVerticalBlockBorderWrapper"] > div > div:has(> [data-testid="stVerticalBlock"]) {
        border: none !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Session-state defaults ────────────────────────────────────────────────────

def _init_state():
    defaults = {
        "lang":              "en",
        "current_conv_id":   None,
        "current_conv_data": None,
        "preview_file":      None,
        "agents":            None,
        "model":             None,
        "formatter":         None,
        "resume_source":     None,
        "specific_file":     None,
        # storage namespaces (initialised on first access by session_store)
        "_output_files":     {},
        "_materials":        {},
        "_conversations_db": {},
        "_interactive_resume": "",
        "_app_settings":     {},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

    # Seed API key from environment variable if not yet set in session
    settings = get_settings()
    if not settings.get("api_key") and os.getenv("OPENAI_API_KEY"):
        save_settings(
            api_key  = os.getenv("OPENAI_API_KEY", ""),
            base_url = os.getenv("OPENAI_BASE_URL", settings["base_url"]),
            model    = os.getenv("OPENAI_MODEL",    settings["model"]),
        )

    # Local mode: seed session_state from existing disk files (one-time per session)
    if not st.session_state.get("_disk_seeded"):
        _seed_from_disk()
        st.session_state["_disk_seeded"] = True


def _seed_from_disk():
    """Load any pre-existing materials/output files and settings from disk into session_state."""
    from config import IS_CLOUD, MATERIALS_DIR, OUTPUT_DIR, ALL_PREVIEW_EXT, SETTINGS_FILE
    from storage.session_store import save_material, save_output_file, get_interactive_resume, save_interactive_resume, get_settings, save_settings

    if IS_CLOUD:
        return

    # Load old settings.json into session if API key not already set
    current = get_settings()
    if not current.get("api_key") and SETTINGS_FILE.exists():
        try:
            import json
            old = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if old.get("api_key"):
                save_settings(
                    api_key           = old.get("api_key", ""),
                    base_url          = old.get("base_url", ""),
                    model             = old.get("model", ""),
                    linkedin_email    = old.get("linkedin_email", ""),
                    linkedin_password = old.get("linkedin_password", ""),
                )
        except Exception:
            pass

    # Load materials
    if MATERIALS_DIR.exists():
        for f in MATERIALS_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ALL_PREVIEW_EXT:
                try:
                    save_material(f.name, f.read_bytes())
                except Exception:
                    pass

    # Load output files
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.iterdir():
            if f.is_file() and f.suffix.lower() in ALL_PREVIEW_EXT:
                try:
                    save_output_file(f.name, f.read_bytes())
                except Exception:
                    pass

    # Load interactive resume if it exists
    from config import DEFAULT_RESUME_FILENAME, CONVERSATIONS_DIR
    resume_path = OUTPUT_DIR / DEFAULT_RESUME_FILENAME
    if resume_path.exists() and not get_interactive_resume():
        try:
            save_interactive_resume(resume_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Restore conversation history from disk JSON files
    if CONVERSATIONS_DIR.exists():
        from storage.conversation_store import ConversationStore
        store = ConversationStore()
        for f in sorted(CONVERSATIONS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                if data.get("id") and data["id"] not in store._db:
                    store._db[data["id"]] = data
            except Exception:
                pass


_init_state()


@st.cache_resource(show_spinner=False)
def _ensure_playwright():
    """Install Playwright Chromium browser once per server process."""
    import subprocess, sys
    try:
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True, text=True, timeout=300,
        )
    except Exception:
        pass


_ensure_playwright()

# ── Auto-create first conversation if none exists ─────────────────────────────
_store = ConversationStore()
if st.session_state.current_conv_id is None:
    existing = _store.list_conversations()
    if existing:
        st.session_state.current_conv_id   = existing[0]["id"]
        st.session_state.current_conv_data = _store.load_conversation(existing[0]["id"])
    else:
        data = _store.new_conversation()
        st.session_state.current_conv_id   = data["id"]
        st.session_state.current_conv_data = data

# ── Custom header row ─────────────────────────────────────────────────────────
title_col, spacer, lang_col, settings_col = st.columns([5, 2, 1, 1])

with title_col:
    st.markdown(f"## {t('app_title')}")

with lang_col:
    if st.button(t("lang_btn"), help="Switch language / 切换语言", use_container_width=True):
        st.session_state.lang = "en" if st.session_state.lang == "zh" else "zh"
        st.rerun()

with settings_col:
    cfg   = get_settings()
    label = t("settings_btn") + (" ✅" if cfg.get("api_key") else " ❗")
    if st.button(label, help=t("settings_help"), use_container_width=True):
        show_settings_dialog()

st.divider()

# ── 3-column layout ───────────────────────────────────────────────────────────
# Left and right panels get fixed-height scrollable containers so they each
# have an independent scrollbar that doesn't affect the other columns.
_PANEL_HEIGHT = 780   # px — adjust to taste for your screen resolution

col_left, col_center, col_right = st.columns([2, 3, 2.5], gap="medium")

with col_left:
    with st.container(height=_PANEL_HEIGHT, border=False):
        render_left_panel()

with col_center:
    render_chat_panel()

with col_right:
    with st.container(height=_PANEL_HEIGHT, border=False):
        render_preview_panel()
