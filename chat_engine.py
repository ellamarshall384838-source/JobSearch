"""
Core agent orchestration logic.

process_message() is the single entry point called by the UI.
Returns: (response_text, updated_session_state, generated_file_names)
  - generated_file_names: list[str] of filenames stored in session output_files

Architecture: Orchestrator acts as a task planner, returning a list of tasks
to execute sequentially. Results from each task are passed as context to the
next, enabling multi-step workflows (e.g. job_search → job_apply_batch).
"""
import re
import json
from pathlib import Path
from typing import Optional

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


# ── Task plan parsing ──────────────────────────────────────────────────────────

_VALID_TASKS = {
    "job_search", "resume_tailor", "resume_generate",
    "interview_prep", "resume_update", "job_apply",
    "job_apply_batch",  # batch apply to URLs produced by a preceding job_search task
    "profile_update",   # update persistent user profile (nationality, visa, phone, etc.)
    "general",
}


def _parse_plan(response) -> list[str]:
    """Parse orchestrator response into an ordered task list."""
    raw = _extract_text(response).strip()
    for fence in ("```json", "```"):
        if fence in raw:
            raw = raw.split(fence, 1)[1].split("```", 1)[0].strip()
            break
    try:
        data = json.loads(raw)
        # New multi-task format: {"tasks": ["job_search", "job_apply_batch"]}
        if "tasks" in data:
            tasks = data["tasks"]
            if isinstance(tasks, list):
                valid = [t.lower().strip() for t in tasks if t.lower().strip() in _VALID_TASKS]
                if valid:
                    return valid
        # Backward-compat: old single-route format {"route": "job_search"}
        route = data.get("route", "").lower().strip()
        if route in _VALID_TASKS:
            return [route]
    except (json.JSONDecodeError, AttributeError):
        pass
    # Regex fallback for old single-route format
    m = re.search(r'"route"\s*:\s*"(\w+)"', raw)
    if m and m.group(1).lower() in _VALID_TASKS:
        return [m.group(1).lower()]
    return []


def _keyword_plan_fallback(text: str) -> list[str]:
    """Keyword-based plan fallback when the orchestrator returns unparseable output."""
    t = text.lower()
    # Compound: search + apply
    # Profile update: nationality / visa / phone / salary info (NOT resume content)
    if any(k in t for k in ("国籍", "签证", "绿卡", "ep", "pr ", "pass", "citizen",
                             "我是.*人", "visa", "work permit", "nationality",
                             "电话", "phone", "期望薪资", "salary expectation")):
        return ["profile_update"]

    has_apply = any(k in t for k in (
        "帮我投", "投简历", "投这个", "申请", "apply", "投递", "一键投", "帮我申请"
    ))
    has_search = any(k in t for k in (
        "找", "搜索", "search", "职位", "岗位", "find", "job"
    ))
    if has_apply and has_search:
        return ["job_search", "job_apply_batch"]

    if any(k in t for k in ("生成简历", "创建简历", "制作简历", "generate resume",
                             "create resume", "make resume", "写一份简历")):
        return ["resume_generate"]
    if any(k in t for k in ("tailor", "optimis", "improve", "cv", "简历优化", "修改简历")):
        return ["resume_tailor"]
    if any(k in t for k in ("interview", "prepare", "question", "star", "面试")):
        return ["interview_prep"]
    if any(k in t for k in ("find", "search", "job", "position", "opening", "搜索", "职位")):
        return ["job_search"]
    if any(k in t for k in ("帮我投", "投简历", "投这个", "申请这个", "apply", "submit application",
                             "投递", "一键投", "帮我申请")):
        return ["job_apply"]
    if any(k in t for k in ("my name", "i graduated", "i worked", "i have",
                             "我叫", "我毕业", "我有", "我的经历")):
        return ["resume_update"]
    return ["general"]


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
    from storage.session_store import save_output_file
    save_output_file(filename, content)


def _try_generate_pdf(md_content: str, stem: str) -> Optional[str]:
    try:
        from tools.pdf_generator import md_to_pdf_bytes
        pdf_bytes = md_to_pdf_bytes(md_content)
        filename  = f"{stem}.pdf"
        _save_output(filename, pdf_bytes)
        return filename
    except Exception as e:
        print(f"[ChatEngine] PDF generation failed: {e}")
        return None


# ── LinkedIn job URL helpers ───────────────────────────────────────────────────

_LINKEDIN_JOB_URL_RE = re.compile(
    r"https?://(?:[\w-]+\.)?linkedin\.com/jobs/(?:view|collections)/[\w\-?=&%/]+",
    re.IGNORECASE,
)
# Also matches ?currentJobId=XXXXX anywhere in a LinkedIn URL
_LINKEDIN_CURRENT_JOB_RE = re.compile(
    r"https?://(?:[\w-]+\.)?linkedin\.com/[^\s]*[?&]currentJobId=(\d+)",
    re.IGNORECASE,
)


def _extract_job_url(text: str) -> Optional[str]:
    # Check for currentJobId= format first
    m2 = _LINKEDIN_CURRENT_JOB_RE.search(text)
    if m2:
        return f"https://www.linkedin.com/jobs/view/{m2.group(1)}/"
    m = _LINKEDIN_JOB_URL_RE.search(text)
    return m.group(0).rstrip(".,)") if m else None


def _parse_job_urls_from_search(raw_search: str) -> list[str]:
    """Extract job URLs from job_search agent output (JSON list with job_link field)."""
    text = raw_search.strip()
    for fence in ("```json", "```"):
        if fence in text:
            text = text.split(fence, 1)[1].split("```", 1)[0].strip()
            break
    try:
        jobs = json.loads(text)
        if isinstance(jobs, list):
            urls = [j["job_link"] for j in jobs if isinstance(j, dict) and j.get("job_link")]
            if urls:
                return urls
    except Exception:
        pass
    # Fallback: regex extraction
    return [m.rstrip(".,)") for m in _LINKEDIN_JOB_URL_RE.findall(raw_search)]


# ── Single-job apply ──────────────────────────────────────────────────────────

def _handle_job_apply(
    user_message: str,
    agents: dict,
    session_state: dict,
    resume_content: str,
) -> str:
    from agentscope.message import Msg
    from async_runner import run_async
    from tools.linkedin_auth import is_session_valid
    from tools.linkedin_applicator import apply_to_job

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

    from tools.user_profile import get_profile, profile_to_text
    user_profile_text = profile_to_text(get_profile())

    def answer_generator(questions: list, resume: str) -> dict:
        resp = run_async(agents["job_applicant"](Msg(
            name="User", role="user",
            content=(
                f"申请表问题列表（JSON 数组）：\n{json.dumps(questions, ensure_ascii=False)}\n\n"
                f"用户简历：\n{resume}\n\n"
                f"{user_profile_text}\n\n"
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
    )

    if resume_pdf_path and resume_pdf_path.exists():
        try:
            _os.unlink(resume_pdf_path)
        except Exception:
            pass

    job_title = apply_result.get("job_title") or "目标职位"
    company   = apply_result.get("company")   or "该公司"
    msg       = apply_result.get("message", "")

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

    # Distinguish non-Easy-Apply failures from other errors
    if "不支持 LinkedIn Easy Apply" in msg or ("Easy Apply" in msg and "不支持" in msg):
        return (
            f"⏭️ **此职位不支持 Easy Apply 自动投递**\n\n"
            f"**职位**: {job_title}\n"
            f"**公司**: {company}\n\n"
            "该职位需要跳转到公司官网填写申请，系统无法自动完成。\n\n"
            f"👉 [点击前往公司官网申请]({job_url})\n\n"
            "💡 **提示**: 如需自动投递，请选择 LinkedIn 页面上标有「Easy Apply」按钮的职位，"
            "或使用「帮我搜索并投递」命令，系统会自动筛选 Easy Apply 职位。"
        )

    return (
        f"⚠️ **申请未能完全自动完成**\n\n"
        f"**原因**: {msg}\n\n"
        "**建议**：\n"
        "- 检查 LinkedIn 登录状态（设置 → 重新登录）\n"
        "- 部分职位需要手动回答额外问题，请在弹出的浏览器中继续操作\n"
        f"- 或直接访问职位页面手动申请：{job_url}"
    )


# ── Batch apply (used after job_search in multi-task plans) ───────────────────

def _do_job_apply_batch(
    job_urls: list[str],
    agents: dict,
    session_state: dict,
    resume_content: str,
    run_async,
    Msg,
) -> str:
    """Apply to all Easy Apply job URLs found by the preceding search task."""
    from tools.linkedin_auth import is_session_valid
    from tools.linkedin_applicator import apply_to_job
    import tempfile
    import os as _os

    if not is_session_valid():
        return (
            "❌ **尚未登录 LinkedIn**，无法执行自动投递。\n\n"
            "请在「⚙️ 设置」中登录后，重新发送搜索并投递的指令。"
        )

    if not job_urls:
        return (
            "⚠️ **搜索结果中没有找到可投递的 Easy Apply 职位链接**\n\n"
            "建议：搜索时使用更多元的关键词，或直接粘贴有「快速申请」的职位链接。"
        )

    # Pre-filter: check each URL for the Easy Apply button using 2 parallel browsers.
    # No LLM needed — pure text detection ("快速申请" / "Easy Apply").
    from tools.linkedin_applicator import filter_easy_apply_urls
    total_before = len(job_urls)
    print(f"[Engine] Filtering {total_before} URLs for Easy Apply...")
    job_urls = filter_easy_apply_urls(job_urls)
    if not job_urls:
        return (
            f"⚠️ **已检查 {total_before} 个职位，暂无 Easy Apply 岗位**\n\n"
            "LinkedIn 大公司（Apple/Google/ByteDance 等）普遍不用 Easy Apply，建议：\n"
            "- 用更垂直的关键词（如 startup、SME 相关职位）\n"
            "- 或直接把有「快速申请」标志的职位链接发给我"
        )
    lines_pre = [f"🔍 已从 {total_before} 个职位中筛出 **{len(job_urls)}** 个 Easy Apply，开始投递...\n"]

    # Prepare resume PDF from session
    resume_pdf_path: Optional[Path] = None
    resume_pdf_name: str = ""
    try:
        from storage.session_store import get_output_files
        output_files = get_output_files()
        pdf_names = sorted(
            [n for n in output_files if n.lower().endswith(".pdf")], reverse=True
        )
        if pdf_names:
            resume_pdf_name = pdf_names[0]
            tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
            tmp.write(output_files[resume_pdf_name])
            tmp.close()
            resume_pdf_path = Path(tmp.name)
    except Exception:
        pass

    from tools.user_profile import get_profile, profile_to_text
    _profile_text = profile_to_text(get_profile())

    def answer_generator(questions: list, resume: str) -> dict:
        resp = run_async(agents["job_applicant"](Msg(
            name="User", role="user",
            content=(
                f"申请表问题列表（JSON 数组）：\n{json.dumps(questions, ensure_ascii=False)}\n\n"
                f"用户简历：\n{resume}\n\n"
                f"{_profile_text}\n\n"
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

    lines = lines_pre + [f"## 🚀 开始批量投递\n"]
    success_count = skip_count = fail_count = 0

    for i, job_url in enumerate(job_urls, 1):
        lines.append(f"\n### [{i}/{len(job_urls)}] 正在投递...")
        apply_result = apply_to_job(
            job_url=job_url,
            resume_path=resume_pdf_path,
            answer_gen=answer_generator,
            resume_content=resume_content,
        )
        job_title = apply_result.get("job_title") or "未知职位"
        company   = apply_result.get("company")   or "未知公司"
        msg       = apply_result.get("message", "")

        if apply_result["success"]:
            success_count += 1
            lines.append(f"✅ **成功**: {job_title} @ {company}")
        elif "不支持 LinkedIn Easy Apply" in msg or ("Easy Apply" in msg and "不支持" in msg):
            # Gracefully skip non-Easy-Apply jobs that slipped through the filter
            skip_count += 1
            lines.append(
                f"⏭️ **跳过**: {job_title} @ {company}（不支持 Easy Apply，需前往官网申请）\n"
                f"   👉 {job_url}"
            )
        else:
            fail_count += 1
            lines.append(f"❌ **失败**: {job_title} @ {company}\n   原因: {msg}")

    if resume_pdf_path and Path(str(resume_pdf_path)).exists():
        try:
            _os.unlink(str(resume_pdf_path))
        except Exception:
            pass

    lines.append(f"\n---\n### 📊 本轮投递汇总\n")
    lines.append(f"- ✅ 成功提交：**{success_count}** 个")
    if skip_count:
        lines.append(f"- ⏭️ 跳过（非 Easy Apply）：**{skip_count}** 个")
    if fail_count:
        lines.append(f"- ❌ 投递失败：**{fail_count}** 个")
    if resume_pdf_name:
        lines.append(f"\n📄 已使用简历文件：`{resume_pdf_name}`")
    if success_count:
        lines.append("\n祝求职顺利！🎉")
    return "\n".join(lines)


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

    The orchestrator returns a task plan (list of tasks). Tasks execute
    sequentially; task_context carries shared data between steps (e.g. job
    URLs from job_search are passed to job_apply_batch).

    Returns:
        (response_text, updated_session_state, generated_file_names)
    """
    generated_files: list[str] = []

    from agentscope.message import Msg
    from async_runner import run_async

    if resume_source is None:
        available     = detect_available_sources(conversation_messages)
        resume_source = available[0] if available else ResumeSource.INTERACTIVE

    resume_content = get_resume_content(
        source=resume_source,
        specific_file=specific_file,
        conversation_messages=conversation_messages,
    )

    # ── Orchestrator: produce task plan ──────────────────────────────────────
    routing_ctx = (
        f"User message: {user_message}\n"
        f"workflow_stage: {session_state.get('workflow_stage', 'discovery')}\n"
        f"selected_job: {session_state.get('selected_job') or 'None'}\n"
        f"last_agent_output: {session_state.get('last_agent_output', '')[:200]}"
    )
    route_resp = run_async(agents["orchestrator"](
        Msg(name="User", content=routing_ctx, role="user")
    ))
    tasks = _parse_plan(route_resp) or _keyword_plan_fallback(user_message)
    print(f"[ChatEngine] tasks → {tasks}")

    # task_context carries data produced by one task into the next
    task_context: dict = {}
    response_parts: list[str] = []

    for task in tasks:
        part = ""

        # ── profile_update ───────────────────────────────────────────────────
        if task == "profile_update":
            from tools.user_profile import get_profile, save_profile, profile_to_text
            current = get_profile()
            resp = run_async(agents["profile_updater"](Msg(
                name="User", role="user",
                content=(
                    f"当前档案：\n{profile_to_text(current)}\n\n"
                    f"用户消息：\n{user_message}\n\n"
                    "请从消息中提取档案字段，输出 JSON。"
                ),
            )))
            raw = _extract_text(resp).strip()
            for fence in ("```json", "```"):
                if fence in raw:
                    raw = raw.split(fence, 1)[1].split("```", 1)[0].strip()
                    break
            try:
                updates = json.loads(raw)
                new_profile = save_profile(updates)
                part = (
                    "✅ **用户档案已更新**\n\n"
                    f"{profile_to_text(new_profile)}\n\n"
                    "此档案将在自动投递时用于填写申请表（国籍、签证状态、电话等）。"
                )
            except Exception:
                part = "❓ 未能解析档案信息，请再描述一次（例如：「我是中国人，持新加坡 EP」）。"

        # ── resume_update ────────────────────────────────────────────────────
        elif task == "resume_update":
            resp = run_async(agents["resume_tailor"](Msg(
                name="User", role="user",
                content=(
                    f"用户提供了以下个人信息：\n{user_message}\n\n"
                    f"当前简历内容（如无则为空）：\n{resume_content}\n\n"
                    "请将新信息整合到简历中，Markdown 格式，放在 <resume_update>…</resume_update> 内，"
                    "标签外附简要确认。"
                ),
            )))
            part = _extract_text(resp)
            updated = _extract_resume_update(part)
            if updated:
                update_interactive_resume(updated)
            session_state["workflow_stage"] = "discovery"

        # ── job_search ───────────────────────────────────────────────────────
        elif task == "job_search":
            # When batch apply follows, search more keywords and more pages
            batch_apply = "job_apply_batch" in tasks

            extra_instr = (
                "请搜索匹配的职位，提取 5 个核心搜索关键词（覆盖多种相关职位名），"
                "调用 fetch_linkedin_jobs 时传入 max_per_keyword=10, num_pages=2。"
                "输出带 job_link 字段的 JSON 列表。"
                if batch_apply else
                "请搜索匹配的职位，输出带 job_link 字段的 JSON 列表。"
            )
            search_resp = run_async(agents["job_search"](Msg(
                name="User", role="user",
                content=(
                    f"用户简历背景：\n{resume_content}\n\n"
                    f"用户请求：\n{user_message}\n\n"
                    f"{extra_instr}"
                ),
            )))
            raw_search = _extract_text(search_resp)

            # Store for context passing to job_apply_batch
            task_context["raw_search"] = raw_search
            task_context["job_urls"]   = _parse_job_urls_from_search(raw_search)

            # Rank and format for display
            rank_resp = run_async(agents["job_post"](Msg(
                name="System", role="user",
                content=(
                    f"用户简历背景：\n{resume_content}\n\n"
                    f"JobSearch 返回的职位数据（JSON）：\n{raw_search}\n\n"
                    "请按匹配度排名，以易读 Markdown 格式（含可点击链接）输出推荐职位列表。"
                ),
            )))
            part = _extract_text(rank_resp)
            session_state["latest_ranked_jobs_json"] = part
            session_state["workflow_stage"] = "discovery"

            if easy_apply_only:
                n = len(task_context["job_urls"])
                part += (
                    f"\n\n> 🔍 已找到 **{n}** 个 Easy Apply 职位，下一步开始自动投递..."
                    if n else
                    "\n\n> ⚠️ 搜索结果中未找到 Easy Apply 职位链接，跳过投递步骤。"
                )

        # ── job_apply_batch ──────────────────────────────────────────────────
        elif task == "job_apply_batch":
            part = _do_job_apply_batch(
                job_urls=task_context.get("job_urls", []),
                agents=agents,
                session_state=session_state,
                resume_content=resume_content,
                run_async=run_async,
                Msg=Msg,
            )
            session_state["workflow_stage"] = "applying"

        # ── resume_tailor ────────────────────────────────────────────────────
        elif task == "resume_tailor":
            resp = run_async(agents["resume_tailor"](Msg(
                name="User", role="user",
                content=(
                    f"用户简历：\n{resume_content}\n\n"
                    f"已推荐职位：\n{session_state.get('latest_ranked_jobs_json', '暂无职位信息')}\n\n"
                    f"目标职位：{session_state.get('selected_job') or '未指定'}\n\n"
                    f"用户请求：\n{user_message}"
                ),
            )))
            part = _extract_text(resp)
            updated = _extract_resume_update(part)
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
                part += (
                    f"\n\n---\n📁 **已保存优化后的简历**（可在左侧「文件」面板查看/下载）：\n{files_info}"
                )
            session_state["workflow_stage"] = "tailoring"

        # ── resume_generate ──────────────────────────────────────────────────
        elif task == "resume_generate":
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
            part       = _extract_text(resp)
            md_content = _extract_resume_update(part)
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
                part += (
                    f"\n\n---\n📁 **已保存文件**（可在左侧「文件」面板查看/预览）：\n{files_info}"
                )
            session_state["workflow_stage"] = "tailoring"

        # ── interview_prep ───────────────────────────────────────────────────
        elif task == "interview_prep":
            resp = run_async(agents["interview_prep"](Msg(
                name="User", role="user",
                content=(
                    f"用户简历：\n{resume_content}\n\n"
                    f"已推荐职位：\n{session_state.get('latest_ranked_jobs_json', '暂无职位信息')}\n\n"
                    f"目标职位：{session_state.get('selected_job') or '未指定'}\n\n"
                    f"用户请求：\n{user_message}"
                ),
            )))
            part = _extract_text(resp)
            session_state["workflow_stage"] = "preparation"

        # ── job_apply (single URL) ───────────────────────────────────────────
        elif task == "job_apply":
            part = _handle_job_apply(user_message, agents, session_state, resume_content)
            session_state["workflow_stage"] = "applying"

        # ── general ──────────────────────────────────────────────────────────
        else:
            part = (
                "您好！我是 **AI 就业简历助手**。我可以帮您：\n\n"
                "- **搜索职位** – 在 LinkedIn 上查找匹配您背景的职位\n"
                "- **生成简历** – 针对特定职位创建定制简历（MD + PDF）\n"
                "- **优化简历** – 对已有简历提出修改建议\n"
                "- **面试准备** – 生成个性化面试问题和 STAR 答题模板\n"
                "- **自动投递** – 登录 LinkedIn 后一键投递指定的 Easy Apply 职位\n"
                "- **搜索并投递** – 自动搜索 Easy Apply 职位并逐一批量投递\n\n"
                "**快速开始：** 上传简历到左侧「材料库」，然后告诉我您想做什么。"
            )

        if part:
            response_parts.append(part)

    response_text = "\n\n---\n\n".join(response_parts) if response_parts else ""
    session_state["last_agent_output"] = response_text[:500]
    return response_text, session_state, generated_files
