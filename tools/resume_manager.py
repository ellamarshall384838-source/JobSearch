"""
Resume source detection and content retrieval.
All storage is read from st.session_state via session_store — no filesystem required.
"""
from typing import Optional
from tools.file_parser import parse_bytes, is_parseable_name, is_image_name


# ── Source identifiers ────────────────────────────────────────────────────────

class ResumeSource:
    INTERACTIVE   = "interactive"
    FULL_SCAN     = "full_scan"
    SPECIFIC_FILE = "specific_file"


SOURCE_LABELS = {
    ResumeSource.INTERACTIVE:   "对话记录 / AI 维护简历",
    ResumeSource.FULL_SCAN:     "材料库全量扫描",
    ResumeSource.SPECIFIC_FILE: "指定文件",
}


# ── Detection ─────────────────────────────────────────────────────────────────

def detect_available_sources(conversation_messages: list) -> list[str]:
    """Return a list of source keys that currently have data."""
    from storage.session_store import get_interactive_resume, get_materials

    sources = []

    # Interactive: AI-maintained résumé text or conversation history
    has_resume = bool(get_interactive_resume())
    has_user_msgs = any(m.get("role") == "user" for m in conversation_messages)
    if has_resume or has_user_msgs:
        sources.append(ResumeSource.INTERACTIVE)

    # Full scan: any parseable non-image file in materials
    materials = get_materials()
    if any(
        is_parseable_name(name) and not is_image_name(name)
        for name in materials
    ):
        sources.append(ResumeSource.FULL_SCAN)

    return sources


# ── Retrieval ─────────────────────────────────────────────────────────────────

def get_resume_content(
    source: str,
    specific_file: Optional[str] = None,
    conversation_messages: Optional[list] = None,
) -> str:
    """Return the résumé text for the given source."""
    from storage.session_store import (
        get_interactive_resume, get_materials,
        get_output_files, get_material, get_output_file,
    )

    if source == ResumeSource.SPECIFIC_FILE:
        if not specific_file:
            return "[错误] 未指定文件名"
        data = get_output_file(specific_file) or get_material(specific_file)
        if data is None:
            return f"[错误] 未找到文件: {specific_file}"
        return parse_bytes(specific_file, data)

    if source == ResumeSource.INTERACTIVE:
        resume_text = get_interactive_resume()
        if resume_text:
            return resume_text
        # Fall back to conversation history
        if conversation_messages:
            user_texts = [
                m["content"] for m in conversation_messages
                if m.get("role") == "user"
            ]
            if user_texts:
                return "用户通过对话提供的信息：\n" + "\n".join(user_texts[:15])
        return ""

    if source == ResumeSource.FULL_SCAN:
        materials = get_materials()
        texts = []
        for name in sorted(materials):
            if is_parseable_name(name) and not is_image_name(name):
                content = parse_bytes(name, materials[name])
                if not content.startswith("["):
                    texts.append(f"--- {name} ---\n{content}")
        return "\n\n".join(texts) if texts else "[材料库中无可解析文件]"

    return ""


# ── Mutation ──────────────────────────────────────────────────────────────────

def update_interactive_resume(content: str) -> None:
    """Update the AI-maintained résumé in session state."""
    from storage.session_store import save_interactive_resume
    save_interactive_resume(content)
