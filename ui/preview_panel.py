"""
Right preview panel: renders the currently selected file from session_state.
preview_file key format: "output::<name>" | "materials::<name>"
Supports PDF, Markdown (rendered/raw toggle), images, TXT, DOCX.
"""
import base64
import streamlit as st
from pathlib import Path

from storage.session_store import get_output_file, get_material, save_output_file
from tools.file_parser import parse_bytes, is_image_name
from ui.i18n import t


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_preview_key(key: str) -> tuple[str, str]:
    """Return (store, filename) from 'output::foo.pdf' or 'materials::bar.md'."""
    if "::" in key:
        store, name = key.split("::", 1)
        return store, name
    return "output", key  # legacy plain-filename fallback


def _get_bytes(store: str, name: str) -> bytes | None:
    if store == "materials":
        return get_material(name)
    return get_output_file(name)


# ── Renderers ─────────────────────────────────────────────────────────────────

def _render_pdf(name: str, data: bytes):
    try:
        b64 = base64.b64encode(data).decode()
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="700px" style="border:none;border-radius:6px;"></iframe>',
            unsafe_allow_html=True,
        )
    except Exception:
        st.warning(t("pdf_embed_fail"))
    st.download_button(t("download_pdf"), data=data, file_name=name, mime="application/pdf")


def _render_markdown(store: str, name: str, data: bytes):
    content  = data.decode("utf-8", errors="replace")
    rendered = st.toggle(t("render_toggle"), value=True, key=f"md_toggle_{name}")
    if rendered:
        st.markdown(content)
    else:
        st.code(content, language="markdown")

    # Edit only available for output files
    if store == "output":
        with st.expander(t("edit_file")):
            new_content = st.text_area(
                t("edit_content"), value=content, height=400, key=f"edit_{name}",
            )
            if st.button(t("save_changes"), key=f"save_{name}"):
                save_output_file(name, new_content.encode("utf-8"))
                st.success(t("saved"))
                st.rerun()


def _render_image(name: str, data: bytes):
    try:
        st.image(data, use_column_width=True)
    except Exception as e:
        st.error(f"{t('img_load_error')}: {e}")


def _render_text(name: str, data: bytes):
    st.code(data.decode("utf-8", errors="replace"), language="text")


def _render_docx(name: str, data: bytes):
    st.text(parse_bytes(name, data))


# ── Public entry point ────────────────────────────────────────────────────────

def render_preview_panel():
    preview_key = st.session_state.get("preview_file")

    if not preview_key:
        st.info(t("preview_empty"))
        return

    store, name = _parse_preview_key(preview_key)
    data = _get_bytes(store, name)

    if data is None:
        st.warning(f"{t('file_missing')}: {name}")
        st.session_state.preview_file = None
        return

    col_name, col_close = st.columns([5, 1])
    with col_name:
        st.markdown(f"**{name}**")
        st.caption("📁 " + ("输出文件" if store == "output" else "材料库"))
    with col_close:
        if st.button(t("close_preview"), key="close_preview", help="Close"):
            st.session_state.preview_file = None
            st.rerun()

    st.divider()

    ext = Path(name).suffix.lower()
    if ext == ".pdf":
        _render_pdf(name, data)
    elif ext == ".md":
        _render_markdown(store, name, data)
    elif is_image_name(name):
        _render_image(name, data)
    elif ext in (".doc", ".docx"):
        _render_docx(name, data)
    elif ext == ".txt":
        _render_text(name, data)
    else:
        st.info(f"{t('unsupported_type')} ({ext})")
        st.download_button(t("download_file"), data=data, file_name=name)
