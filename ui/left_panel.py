"""
Left panel: conversation management (Tab 1) + output file management (Tab 2)
            + materials library (bottom section).
All file data lives in st.session_state with write-through to disk (local mode).
"""
from pathlib import Path
import streamlit as st

from storage.conversation_store import ConversationStore
from storage.session_store import (
    get_output_files, save_output_file, delete_output_file, rename_output_file,
    get_materials, save_material, delete_material,
)
from tools.file_parser import is_image_name
from ui.i18n import t

_store = ConversationStore()


# ── File icon ─────────────────────────────────────────────────────────────────

def _file_icon(name: str) -> str:
    ext = Path(name).suffix.lower()
    if ext == ".pdf":             return "📄"
    if ext == ".md":              return "📝"
    if ext in (".doc", ".docx"): return "📃"
    if is_image_name(name):      return "🖼️"
    return "📎"


# ── Conversation tab ──────────────────────────────────────────────────────────

def _render_conversations_tab():
    if st.button(t("new_chat"), use_container_width=True, type="primary"):
        data = _store.new_conversation(title=t("new_conv_title"))
        st.session_state.current_conv_id   = data["id"]
        st.session_state.current_conv_data = data
        st.session_state.resume_source     = None
        st.rerun()

    st.divider()
    conversations = _store.list_conversations()

    if not conversations:
        st.caption(t("no_chats"))
        return

    for conv in conversations:
        is_active = conv["id"] == st.session_state.get("current_conv_id")

        col_title, col_del = st.columns([5, 1])
        with col_title:
            label = ("▶ " if is_active else "") + conv["title"]
            if st.button(label, key=f"conv_{conv['id']}", use_container_width=True,
                         help=conv.get("updated_at", "")[:19]):
                st.session_state.current_conv_id   = conv["id"]
                st.session_state.current_conv_data = _store.load_conversation(conv["id"])
                st.rerun()
        with col_del:
            if st.button("🗑", key=f"del_conv_{conv['id']}", help=t("delete_help")):
                _store.delete_conversation(conv["id"])
                if st.session_state.get("current_conv_id") == conv["id"]:
                    st.session_state.current_conv_id   = None
                    st.session_state.current_conv_data = None
                st.rerun()


# ── Shared file row renderer (avoids 3-deep column nesting) ──────────────────
#
# Streamlit allows columns nested ONE level inside another column.
# app.py → col_left (level 1) → st.columns([5,1,1,1]) (level 2, max allowed).
# We must NOT create a third level like: col_acts → st.columns(3).

def _render_file_row(name: str, data: bytes, store: str):
    """
    Render one file row with a flat 4-column layout:
      [icon+name  |  ⬇  |  ✏/→  |  🗑]
    store: "output" or "materials"
    """
    is_selected = st.session_state.get("preview_file") == f"{store}::{name}"
    icon  = _file_icon(name)
    label = f"{icon} **{name}**" if is_selected else f"{icon} {name}"

    # Single-level column split (level 2 inside col_left) — no further nesting
    c_name, c_dl, c_act, c_del = st.columns([5, 1, 1, 1])

    with c_name:
        if st.button(label, key=f"{store}_{name}_preview",
                     use_container_width=True, help=t("preview_help")):
            st.session_state.preview_file = f"{store}::{name}"
            st.rerun()

    with c_dl:
        st.download_button(
            t("download"), data=data, file_name=name,
            key=f"{store}_{name}_dl", help=t("download_help"),
        )

    with c_act:
        if store == "output":
            if st.button("✏", key=f"{store}_{name}_ren", help=t("rename_help")):
                st.session_state[f"rename_{store}_{name}"] = True
        else:
            # materials → move to output
            if st.button("→", key=f"{store}_{name}_move", help=t("move_to_output_help")):
                save_output_file(name, data)
                delete_material(name)
                if st.session_state.get("preview_file") == f"materials::{name}":
                    st.session_state.preview_file = None
                st.rerun()

    with c_del:
        if st.button("🗑", key=f"{store}_{name}_del", help=t("delete_help")):
            if st.session_state.get("preview_file") == f"{store}::{name}":
                st.session_state.preview_file = None
            if store == "output":
                delete_output_file(name)
            else:
                delete_material(name)
            st.rerun()

    # Inline rename (output only) — full width, no extra columns
    rename_key = f"rename_{store}_{name}"
    if st.session_state.get(rename_key):
        new_name = st.text_input(t("rename_label"), value=name,
                                 key=f"new_name_{store}_{name}")
        c_ok, c_cancel = st.columns(2)
        with c_ok:
            if st.button(t("confirm"), key=f"rename_ok_{store}_{name}"):
                if new_name and new_name != name:
                    rename_output_file(name, new_name)
                    if st.session_state.get("preview_file") == f"output::{name}":
                        st.session_state.preview_file = f"output::{new_name}"
                st.session_state.pop(rename_key, None)
                st.rerun()
        with c_cancel:
            if st.button(t("cancel"), key=f"rename_cancel_{store}_{name}"):
                st.session_state.pop(rename_key, None)
                st.rerun()

    # Move to materials (output only) — full-width button, no extra columns
    if store == "output":
        if st.button(t("move_to_materials"), key=f"{store}_{name}_to_mat",
                     use_container_width=False):
            save_material(name, data)
            delete_output_file(name)
            if st.session_state.get("preview_file") == f"output::{name}":
                st.session_state.preview_file = None
            st.rerun()

    st.markdown("---")


# ── Output files tab ──────────────────────────────────────────────────────────

def _render_output_files_tab():
    st.caption(t("output_caption"))

    # Key rotation: after processing, increment key so the widget resets and
    # won't re-trigger on the next rerun (fixes infinite-refresh bug).
    _uk = st.session_state.get("_ul_out_key", 0)
    uploaded = st.file_uploader(
        t("upload_files"),
        accept_multiple_files=True,
        key=f"upload_output_{_uk}",
        label_visibility="collapsed",
    )
    if uploaded:
        for f in uploaded:
            save_output_file(f.name, f.getbuffer().tobytes())
        st.session_state["_ul_out_key"] = _uk + 1  # reset uploader next rerun
        st.rerun()

    st.divider()
    files = get_output_files()

    if not files:
        st.caption(t("output_empty"))
        return

    for name in sorted(files):
        _render_file_row(name, files[name], "output")


# ── Materials section ─────────────────────────────────────────────────────────

def _render_materials_section():
    with st.expander(t("materials_header"), expanded=True):
        st.caption(t("materials_caption"))

        _mk = st.session_state.get("_ul_mat_key", 0)
        uploaded = st.file_uploader(
            t("upload_files"),
            accept_multiple_files=True,
            key=f"upload_materials_{_mk}",
            label_visibility="collapsed",
        )
        if uploaded:
            for f in uploaded:
                save_material(f.name, f.getbuffer().tobytes())
            st.session_state["_ul_mat_key"] = _mk + 1  # reset uploader next rerun
            st.rerun()

        st.divider()
        materials = get_materials()

        if not materials:
            st.caption(t("materials_empty"))
            return

        for name in sorted(materials):
            _render_file_row(name, materials[name], "materials")


# ── LinkedIn status section ───────────────────────────────────────────────────

def _render_linkedin_section():
    with st.expander(t("linkedin_status_header"), expanded=False):
        from tools.linkedin_auth import is_session_valid, get_logged_in_email
        from tools.linkedin_applicator import load_applications_log

        if is_session_valid():
            email = get_logged_in_email()
            st.success(f"✅ {email or t('linkedin_logged_in')}")
        else:
            st.warning(f"⚠️ {t('linkedin_not_logged_in')}")
            st.caption(t("linkedin_go_settings"))

        log = load_applications_log()
        if log:
            st.markdown(f"**{t('linkedin_apply_history')}** ({len(log)} {t('linkedin_apply_count')})")
            for rec in reversed(log[-5:]):
                icon    = "✅" if rec.get("success") else "❌"
                title   = rec.get("job_title") or t("linkedin_unknown_job")
                company = rec.get("company", "")
                ts      = rec.get("timestamp", "")[:10]
                url     = rec.get("url", "")
                line    = f"{icon} **{title}**"
                if company:
                    line += f" @ {company}"
                if ts:
                    line += f" _{ts}_"
                st.markdown(f"{line}  \n[🔗]({url})" if url else line)
            if len(log) > 5:
                st.caption(t("linkedin_more_records").format(n=len(log) - 5))
        else:
            st.caption(t("linkedin_no_applications"))


# ── Public entry point ────────────────────────────────────────────────────────

def render_left_panel():
    tab_conv, tab_files = st.tabs([t("tab_conversations"), t("tab_files")])
    with tab_conv:
        _render_conversations_tab()
    with tab_files:
        _render_output_files_tab()

    st.divider()
    _render_linkedin_section()

    st.divider()
    _render_materials_section()
