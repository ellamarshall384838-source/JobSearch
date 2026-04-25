"""
Core agent orchestration logic.

process_message() is the single entry point called by the UI.
Returns: (response_text, updated_session_state, generated_file_names)
  - generated_file_names: list[str] of filenames stored in session output_files
"""
import re
import json
from pathlib import Path
from typing import Optional

from agentscope.message import Msg

from async_runner import run_async
from tools.resume_manager import (
    get_resume_content,
    update_interactive_resume,
    detect_available_sources,
    ResumeSource,
    SOURCE_LABELS,
)


# ── Text extraction ────────────────────────────────────────────────────────────

def _extract_text(response) -> str:
    raw = response.content
    if isinstance(raw, list):
        return "".join(item.get("text", "") for item in raw if item.get("type") == "text")
    return str(raw)


# ── Route parsing ──────────────────────────────────────────────────────────────

_VALID_ROUTES = {
    "job_search", "resume_tailor", "resume_generate",
    "interview_prep", "resume_update", "job_apply", "general",
}


def _parse_route(response) -> str:
    raw = _extract_text(response).strip()
    for fence in ("```json", "```"):
        if fence in raw:
            raw = raw.split(fence, 1)[1].split("```", 1)[0].strip()
            break
    try:
        data  = json.loads(raw)
        route = data.get("route", "").lower().strip()
        if route in _VALID_ROUTES:
            return route
    except (json.JSONDecodeError, AttributeError):
        pass
    m = re.search(r'"route"\s*:\s*"(\w+)"', raw)
    if m and m.group(1).lower() in _VALID_ROUTES:
        return m.group(1).lower()
    return ""


def _keyword_fallback(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("生成简历", "创建简历", "制作简历", "generate resume",
                             "create resume", "make resume", "写一份简历")):
        return "resume_generate"
    if any(k in t for k in ("tailor", "optimis", "improve", "cv", "简历优化", "修改简历")):
        return "resume_tailor"
    if any(k in t for k in ("interview", "prepare", "question", "star", "面试")):
        return "interview_prep"
    if any(k in t for k in ("find", "search", "job", "position", "opening", "搜索", "职位")):
        return "job_search"
    if any(k in t for k in ("帮我投", "投简历", "投这个", "申请这个", "apply", "submit application",
                             "投递", "一键投", "帮我申请")):
        return "job_apply"
    if any(k in t for k in ("my name", "i graduated", "i worked", "i have",
                             "我叫", "我毕业", "我有", "我的经历")):
        return "resume_update"
    return "general"


# ── Content helpers ────────────────────────────────────────────────────────────

def _extract_resume_update(text: str) -> Optional[str]:
    m = re.search(r"<resume_update>(.*?)</resume_update>", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _extract_job_info(ranked_text: str) -> tuple[str, str]:
    m = re.search(r"###\s+\d+\.\s+(.+?)\s+@\s+(.+?)[\n$]", ranked_text)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return "", ""


def _save_output(filename: str, content: "str | bytes") -> None:
    """Store a generated file in session_state (no filesystem write)."""
    from storage.session_store import save_output_file
    save_output_file(filename, content)


def _try_generate_pdf(md_content: str, stem: str) -> Optional[str]:
    """Generate PDF bytes, store in session, return filename or None."""
    try:
        from tools.pdf_generator import md_to_pdf_bytes
        pdf_bytes = md_to_pdf_bytes(md_content)
        filename  = f"{stem}.pdf"
        _save_output(filename, pdf_bytes)
        return filename
    except Exception as e:
        print(f"[ChatEngine] PDF generation failed: {e}")
        return None


# ── LinkedIn job apply ────────────────────────────────────────────────────────

_LINKEDIN_JOB_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/jobs/(?:view|collections)/[\w\-?=&%]+",
    re.IGNORECASE,
)


def _extract_job_url(text: str) -> Optional[str]:
    m = _LINKEDIN_JOB_URL_RE.search(text)
    return m.group(0).rstrip(".,)") if m else None


def _handle_job_apply(
    user_message: str,
    agents: dict,
    session_state: dict,
    resume_content: str,
) -> str:
    from config import IS_CLOUD
    if IS_CLOUD:
        return (
            "⚠️ **云端部署不支持自动投简历功能**\n\n"
            "LinkedIn Easy Apply 需要本地 Chrome 浏览器。\n"
            "请在本地运行此应用以使用自动投递功能，或直接访问 LinkedIn 手动申请。"
        )

    from tools.linkedin_auth import is_session_valid
    from tools.linkedin_applicator import apply_to_job, get_best_resume_pdf

    if not is_session_valid():
        return (
            "❌ **尚未登录 LinkedIn**\n\n"
            "请按以下步骤操作：\n"
            "1. 点击右上角 **⚙️ 设置**\n"
            "2. 在「LinkedIn 账号」部分填写您的邮箱和密码\n"
            "3. 点击「登录 LinkedIn」，在弹出的浏览器中完成授权\n\n"
            "登录成功后，再次发送投递指令即可自动投递简历。"
        )

    job_url = (
        _extract_job_url(user_message)
        or _extract_job_url(session_state.get("latest_ranked_jobs_json", ""))
    )

    if not job_url:
        ranked = session_state.get("latest_ranked_jobs_json", "")
        if ranked:
            return (
                "❓ **请指定要投递的职位链接**\n\n"
                "请将想投递的职位链接发给我，例如：\n"
                "> `帮我投这个：https://www.linkedin.com/jobs/view/...`"
            )
        return (
            "❓ **请先搜索职位，再告诉我要投哪个**\n\n"
            "1. 发送「帮我搜索 [职位名称] 的工作」\n"
            "2. 从结果中找到心仪职位\n"
            "3. 发送「帮我投这个」或直接粘贴职位链接"
        )

    def answer_generator(questions: list, resume: str) -> dict:
        resp = run_async(agents["job_applicant"](Msg(
            name="User", role="user",
            content=(
                f"申请表问题列表（JSON 数组）：\n{json.dumps(questions, ensure_ascii=False)}\n\n"
                f"用户简历：\n{resume}\n\n"
                "请返回合法 JSON 对象，键为问题原文，值为回答。"
            ),
        )))
        raw = _extract_text(resp).strip()
        for fence in ("```json", "```"):
            if fence in raw:
                raw = raw.split(fence, 1)[1].split("```", 1)[0].strip()
                break
        try:
            return json.loads(raw)
        except Exception:
            return {}

    # Write best PDF from session to a temp file for Playwright upload
    import tempfile
    import os as _os
    resume_pdf_path: Optional[Path] = None
    resume_pdf_name: str = ""
    try:
        from storage.session_store import get_output_files
        output_files = get_output_files()
        pdf_names = sorted(
            [n for n in output_files if n.lower().endswith(".pdf")],
            reverse=True,
        )
        if pdf_names:
            resume_pdf_name = pdf_names[0]
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(output_files[resume_pdf_name])
            tmp.close()
            resume_pdf_path = Path(tmp.name)
    except Exception:
        pass

    apply_result = apply_to_job(
        job_url=job_url,
        resume_path=resume_pdf_path,
        answer_gen=answer_generator,
        resume_content=resume_content,
        headless=False,
    )

    # Clean up temp file
    if resume_pdf_path and resume_pdf_path.exists():
        try:
            _os.unlink(resume_pdf_path)
        except Exception:
            pass

    job_title = apply_result.get("job_title") or "目标职位"
    company   = apply_result.get("company")   or "该公司"

    if apply_result["success"]:
        pdf_note = f"\n\n📄 **已上传简历**: `{resume_pdf_name}`" if resume_pdf_name else ""
        return (
            f"✅ **申请已成功提交！**\n\n"
            f"**职位**: {job_title}\n"
            f"**公司**: {company}\n"
            f"**链接**: {job_url}"
            f"{pdf_note}\n\n"
            "申请记录已保存到本地日志。祝您求职顺利！🎉"
        )
    return (
        f"⚠️ **申请未能完全自动完成**\n\n"
        f"**原因**: {apply_result['message']}\n\n"
        "**建议**：\n"
        "- 检查 LinkedIn 登录状态（设置 → 重新登录）\n"
        "- 部分职位需要手动回答额外问题，请在弹出的浏览器中继续操作\n"
        f"- 或直接访问职位页面手动申请：{job_url}"
    )


# ── Conflict detection ────────────────────────────────────────────────────────

def check_resume_source_conflict(
    conversation_messages: list,
    current_source: Optional[str],
) -> Optional[str]:
    if current_source is not None:
        return None
    available = detect_available_sources(conversation_messages)
    if len(available) < 2:
        return None
    labels = [f"• **{SOURCE_LABELS[s]}**" for s in available]
    return (
        "检测到多个简历来源，请问您希望我基于哪个进行操作？\n\n"
        + "\n".join(labels)
        + "\n\n请在上方「简历来源」选择器中选择，或直接告诉我。"
    )


# ── Main entry point ──────────────────────────────────────────────────────────

def process_message(
    user_message: str,
    agents: dict,
    session_state: dict,
    conversation_messages: list,
    resume_source: str,
    specific_file: Optional[str] = None,
) -> tuple[str, dict, list[str]]:
    """
    Route user_message through the agent pipeline.

    Returns:
        (response_text, updated_session_state, generated_file_names)
        generated_file_names: list[str] — filenames saved to session output_files
    """
    generated_files: list[str] = []

    if resume_source is None:
        available     = detect_available_sources(conversation_messages)
        resume_source = available[0] if available else ResumeSource.INTERACTIVE

    resume_content = get_resume_content(
        source=resume_source,
        specific_file=specific_file,
        conversation_messages=conversation_messages,
    )

    # ── Orchestrator routing ──────────────────────────────────────────────────
    routing_ctx = (
        f"User message: {user_message}\n"
        f"workflow_stage: {session_state.get('workflow_stage', 'discovery')}\n"
        f"selected_job: {session_state.get('selected_job') or 'None'}\n"
        f"last_agent_output: {session_state.get('last_agent_output', '')[:200]}"
    )
    route_resp = run_async(agents["orchestrator"](
        Msg(name="User", content=routing_ctx, role="user")
    ))
    route = _parse_route(route_resp) or _keyword_fallback(user_message)
    print(f"[ChatEngine] route → {route}")

    response_text = ""

    # ── Dispatch ──────────────────────────────────────────────────────────────

    if route == "resume_update":
        resp = run_async(agents["resume_tailor"](Msg(
            name="User", role="user",
            content=(
                f"用户提供了以下个人信息：\n{user_message}\n\n"
                f"当前简历内容（如无则为空）：\n{resume_content}\n\n"
                "请将新信息整合到简历中，Markdown 格式，放在 <resume_update>…</resume_update> 内，"
                "标签外附简要确认。"
            ),
        )))
        response_text = _extract_text(resp)
        updated = _extract_resume_update(response_text)
        if updated:
            update_interactive_resume(updated)
        session_state["workflow_stage"] = "discovery"

    elif route == "job_search":
        search_resp = run_async(agents["job_search"](Msg(
            name="User", role="user",
            content=(
                f"用户简历背景：\n{resume_content}\n\n"
                f"用户请求：\n{user_message}\n\n"
                "请搜索匹配的职位，输出带 job_link 字段的 JSON 列表。"
            ),
        )))
        raw_search = _extract_text(search_resp)

        resp = run_async(agents["job_post"](Msg(
            name="System", role="user",
            content=(
                f"用户简历背景：\n{resume_content}\n\n"
                f"JobSearch 返回的职位数据（JSON）：\n{raw_search}\n\n"
                "请按匹配度排名，以易读 Markdown 格式（含可点击链接）输出推荐职位列表。"
            ),
        )))
        response_text = _extract_text(resp)
        session_state["latest_ranked_jobs_json"] = response_text
        session_state["workflow_stage"] = "discovery"

    elif route == "resume_tailor":
        resp = run_async(agents["resume_tailor"](Msg(
            name="User", role="user",
            content=(
                f"用户简历：\n{resume_content}\n\n"
                f"已推荐职位：\n{session_state.get('latest_ranked_jobs_json', '暂无职位信息')}\n\n"
                f"目标职位：{session_state.get('selected_job') or '未指定'}\n\n"
                f"用户请求：\n{user_message}"
            ),
        )))
        response_text = _extract_text(resp)
        updated = _extract_resume_update(response_text)
        if updated:
            update_interactive_resume(updated)
            job_title, company = _extract_job_info(
                session_state.get("latest_ranked_jobs_json", "")
            )
            from tools.pdf_generator import make_resume_filename
            stem    = make_resume_filename(job_title, company)
            md_name = f"{stem}.md"
            _save_output(md_name, updated)
            generated_files.append(md_name)
            pdf_name = _try_generate_pdf(updated, stem)
            if pdf_name:
                generated_files.append(pdf_name)
            files_info = "\n".join(f"- `{n}`" for n in generated_files)
            response_text += (
                f"\n\n---\n📁 **已保存优化后的简历**（可在左侧「文件」面板查看/下载）：\n{files_info}"
            )
        session_state["workflow_stage"] = "tailoring"

    elif route == "resume_generate":
        job_context = (
            session_state.get("latest_ranked_jobs_json", "") or
            session_state.get("selected_job") or
            ""
        )
        resp = run_async(agents["resume_generator"](Msg(
            name="User", role="user",
            content=(
                f"用户背景信息：\n{resume_content}\n\n"
                f"目标职位信息：\n{job_context}\n\n"
                f"用户请求：\n{user_message}\n\n"
                "请创建一份完整的、针对该职位的 Markdown 简历，"
                "放在 <resume_update>…</resume_update> 标签内。"
            ),
        )))
        response_text = _extract_text(resp)
        md_content    = _extract_resume_update(response_text)

        if md_content:
            job_title, company = _extract_job_info(job_context)
            from tools.pdf_generator import make_resume_filename
            stem    = make_resume_filename(job_title, company)
            md_name = f"{stem}.md"
            _save_output(md_name, md_content)
            generated_files.append(md_name)
            update_interactive_resume(md_content)
            pdf_name = _try_generate_pdf(md_content, stem)
            if pdf_name:
                generated_files.append(pdf_name)
            files_info = "\n".join(f"- `{n}`" for n in generated_files)
            response_text += (
                f"\n\n---\n📁 **已保存文件**（可在左侧「文件」面板查看/预览）：\n{files_info}"
            )
        session_state["workflow_stage"] = "tailoring"

    elif route == "interview_prep":
        resp = run_async(agents["interview_prep"](Msg(
            name="User", role="user",
            content=(
                f"用户简历：\n{resume_content}\n\n"
                f"已推荐职位：\n{session_state.get('latest_ranked_jobs_json', '暂无职位信息')}\n\n"
                f"目标职位：{session_state.get('selected_job') or '未指定'}\n\n"
                f"用户请求：\n{user_message}"
            ),
        )))
        response_text = _extract_text(resp)
        session_state["workflow_stage"] = "preparation"

    elif route == "job_apply":
        response_text = _handle_job_apply(
            user_message, agents, session_state, resume_content
        )
        session_state["workflow_stage"] = "applying"

    else:  # general
        response_text = (
            "您好！我是 **AI 就业简历助手**。我可以帮您：\n\n"
            "- **搜索职位** – 在 LinkedIn 上查找匹配您背景的职位\n"
            "- **生成简历** – 针对特定职位创建定制简历（MD + PDF）\n"
            "- **优化简历** – 对已有简历提出修改建议\n"
            "- **面试准备** – 生成个性化面试问题和 STAR 答题模板\n"
            "- **自动投递** – 登录 LinkedIn 后可一键投递 Easy Apply 职位\n\n"
            "**快速开始：** 上传简历到左侧「材料库」，然后告诉我您想做什么。"
        )

    session_state["last_agent_output"] = response_text[:500]
    return response_text, session_state, generated_files
