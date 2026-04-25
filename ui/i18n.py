"""
Internationalisation: all user-visible UI strings in Chinese and English.
Usage: from ui.i18n import t
       label = t("new_chat")
"""
import streamlit as st

TEXTS: dict[str, dict[str, str]] = {
    # ── app.py ────────────────────────────────────────────────────────────────
    "app_title":            {"zh": "🎯 AI 就业简历助手",         "en": "🎯 AI Job Search Assistant"},
    "settings_btn":         {"zh": "⚙️ 设置",                   "en": "⚙️ Settings"},
    "settings_help":        {"zh": "配置 API Key 和模型",         "en": "Configure API key & model"},
    "lang_btn":             {"zh": "🌐 English",                "en": "🌐 中文"},

    # ── left_panel.py ─────────────────────────────────────────────────────────
    "tab_conversations":    {"zh": "💬 对话",                    "en": "💬 Chats"},
    "tab_files":            {"zh": "📁 文件",                    "en": "📁 Files"},
    "new_chat":             {"zh": "＋ 新建对话",                 "en": "＋ New Chat"},
    "new_conv_title":       {"zh": "新对话",                     "en": "New Conversation"},
    "no_chats":             {"zh": "暂无对话，点击上方按钮新建",    "en": "No chats yet. Click above to create one."},
    "output_caption":       {"zh": "AI 可读写此目录下的 .md 文件", "en": "AI can read/write .md files here"},
    "upload_files":         {"zh": "拖拽或选择文件上传",           "en": "Drag & drop or browse files"},
    "output_empty":         {"zh": "输出目录为空",                "en": "Output directory is empty"},
    "preview_help":         {"zh": "点击预览",                   "en": "Click to preview"},
    "download":             {"zh": "⬇",                         "en": "⬇"},
    "rename":               {"zh": "✏",                         "en": "✏"},
    "delete":               {"zh": "🗑",                         "en": "🗑"},
    "rename_label":         {"zh": "新文件名",                   "en": "New filename"},
    "confirm":              {"zh": "确认",                       "en": "Confirm"},
    "cancel":               {"zh": "取消",                       "en": "Cancel"},
    "move_to_materials":    {"zh": "→ 移至材料库",               "en": "→ Move to Materials"},
    "move_to_output":       {"zh": "→",                         "en": "→"},
    "move_to_output_help":  {"zh": "移至输出目录",               "en": "Move to output"},
    "materials_header":     {"zh": "📚 材料库（只读材料，AI 仅读取）", "en": "📚 Materials (read-only for AI)"},
    "materials_caption":    {"zh": "上传原始简历、证书、项目说明等背景材料",
                             "en": "Upload original resumes, certificates, project briefs, etc."},
    "materials_empty":      {"zh": "材料库为空",                 "en": "Materials directory is empty"},
    "delete_help":          {"zh": "删除",                       "en": "Delete"},
    "download_help":        {"zh": "下载",                       "en": "Download"},
    "rename_help":          {"zh": "重命名",                     "en": "Rename"},

    # ── chat_panel.py ─────────────────────────────────────────────────────────
    "select_chat":          {"zh": "👈 请在左侧新建或选择一个对话",
                             "en": "👈 Create or select a conversation on the left"},
    "no_api_key":           {"zh": "⚙️ 请先点击右上角「设置」，填写 API Key 后再开始对话。",
                             "en": "⚙️ Please click ⚙️ Settings (top-right) to enter your API Key first."},
    "resume_source_label":  {"zh": "简历来源",                   "en": "Resume Source"},
    "select_file_label":    {"zh": "选择文件",                   "en": "Select file"},
    "no_files_hint":        {"zh": "（两个目录均无文件）",         "en": "(No files in either directory)"},
    "chat_placeholder":     {"zh": "输入消息…",                  "en": "Type a message…"},
    "no_api_error":         {"zh": "请先在设置中配置有效的 API Key。",
                             "en": "Please configure a valid API Key in Settings first."},
    "thinking":             {"zh": "AI 正在思考…",               "en": "AI is thinking…"},
    "error_prefix":         {"zh": "[错误]",                     "en": "[Error]"},

    # ── preview_panel.py ──────────────────────────────────────────────────────
    "preview_empty":        {"zh": "👈 点击左侧文件名即可在此预览",
                             "en": "👈 Click any filename on the left to preview it here"},
    "file_missing":         {"zh": "文件已不存在",                "en": "File no longer exists"},
    "close_preview":        {"zh": "✕",                         "en": "✕"},
    "render_toggle":        {"zh": "渲染模式",                   "en": "Rendered"},
    "edit_file":            {"zh": "✏️ 编辑此文件",              "en": "✏️ Edit this file"},
    "edit_content":         {"zh": "内容",                       "en": "Content"},
    "save_changes":         {"zh": "保存修改",                   "en": "Save changes"},
    "saved":                {"zh": "已保存！",                   "en": "Saved!"},
    "img_load_error":       {"zh": "图片加载失败",                "en": "Image failed to load"},
    "unsupported_type":     {"zh": "不支持预览此文件类型",         "en": "Preview not supported for this file type"},
    "download_pdf":         {"zh": "⬇ 下载 PDF",                "en": "⬇ Download PDF"},
    "download_file":        {"zh": "⬇ 下载文件",                 "en": "⬇ Download file"},
    "pdf_embed_fail":       {"zh": "无法嵌入 PDF 预览，请使用下方下载按钮。",
                             "en": "Cannot embed PDF. Use the download button below."},

    # ── resume generation ─────────────────────────────────────────────────────
    "resume_generated_ok":  {"zh": "✅ 简历已生成并保存，可在左侧「文件」面板预览下载。",
                             "en": "✅ Resume generated and saved. Preview it in the Files panel on the left."},

    # ── LinkedIn (settings_dialog + left_panel) ──────────────────────────────
    "linkedin_section_header":  {"zh": "### 🔗 LinkedIn 账号",
                                 "en": "### 🔗 LinkedIn Account"},
    "linkedin_section_caption": {"zh": "登录 LinkedIn 账号后，AI 可代您自动投递 Easy Apply 职位",
                                 "en": "Log in so the AI can auto-submit Easy Apply jobs on your behalf"},
    "linkedin_logged_in":       {"zh": "已登录",                "en": "Logged in"},
    "linkedin_not_logged_in":   {"zh": "未登录 LinkedIn",       "en": "Not logged in to LinkedIn"},
    "linkedin_unknown_email":   {"zh": "账号已连接",             "en": "Account connected"},
    "linkedin_email_label":     {"zh": "LinkedIn 邮箱",         "en": "LinkedIn Email"},
    "linkedin_password_label":  {"zh": "LinkedIn 密码",         "en": "LinkedIn Password"},
    "linkedin_login_btn":       {"zh": "登录 LinkedIn",         "en": "Log in to LinkedIn"},
    "linkedin_logout_btn":      {"zh": "退出登录",              "en": "Log out"},
    "linkedin_no_creds":        {"zh": "请填写邮箱和密码",       "en": "Please enter email and password"},
    "linkedin_browser_opening": {"zh": "正在打开浏览器，请在弹出的 Chrome 窗口中完成登录（如有验证码请手动处理）…",
                                 "en": "Opening browser — please complete login in the Chrome window (handle any CAPTCHA manually)…"},
    "linkedin_logging_in":      {"zh": "等待 LinkedIn 登录完成（最长 4 分钟）…",
                                 "en": "Waiting for LinkedIn login (up to 4 minutes)…"},
    "linkedin_logged_out":      {"zh": "已退出 LinkedIn 登录",  "en": "Logged out of LinkedIn"},
    "linkedin_tos_note":        {"zh": "⚠️ 仅用于个人求职，请遵守 LinkedIn 使用条款。本工具仅支持「Easy Apply」职位。",
                                 "en": "⚠️ For personal job searching only. Please comply with LinkedIn's Terms of Service. Only 'Easy Apply' jobs are supported."},
    "linkedin_status_header":   {"zh": "🔗 LinkedIn 状态",      "en": "🔗 LinkedIn Status"},
    "linkedin_go_settings":     {"zh": "前往「⚙️ 设置」登录您的 LinkedIn 账号",
                                 "en": "Go to ⚙️ Settings to log in to your LinkedIn account"},
    "linkedin_apply_history":   {"zh": "投递记录",              "en": "Application History"},
    "linkedin_apply_count":     {"zh": "条",                    "en": "records"},
    "linkedin_unknown_job":     {"zh": "未知职位",              "en": "Unknown job"},
    "linkedin_no_applications": {"zh": "暂无投递记录",           "en": "No applications yet"},
    "linkedin_more_records":    {"zh": "还有 {n} 条更早的记录",  "en": "{n} more earlier records"},

    # ── settings_dialog.py ────────────────────────────────────────────────────
    "settings_title":       {"zh": "设置 / Settings",           "en": "Settings"},
    "api_config_header":    {"zh": "### API 配置",               "en": "### API Configuration"},
    "api_caption":          {"zh": "支持任何兼容 OpenAI 协议的 API 端点（Gemini、OpenAI、本地 Ollama 等）",
                             "en": "Supports any OpenAI-compatible endpoint (Gemini, OpenAI, local Ollama, etc.)"},
    "api_key_label":        {"zh": "API Key",                    "en": "API Key"},
    "api_key_placeholder":  {"zh": "sk-... 或 Gemini API Key",  "en": "sk-... or Gemini API Key"},
    "base_url_label":       {"zh": "Base URL（留空使用 OpenAI 默认端点）",
                             "en": "Base URL (leave blank for default OpenAI endpoint)"},
    "model_label":          {"zh": "模型名称",                   "en": "Model name"},
    "test_btn":             {"zh": "测试连接",                   "en": "Test Connection"},
    "no_api_key_warn":      {"zh": "请先输入 API Key",           "en": "Please enter an API Key first"},
    "testing":              {"zh": "正在测试…",                  "en": "Testing…"},
    "save_btn":             {"zh": "保存",                       "en": "Save"},
    "saved_msg":            {"zh": "设置已保存！",               "en": "Settings saved!"},
    "cancel_btn":           {"zh": "取消",                       "en": "Cancel"},
}


def t(key: str) -> str:
    """Return the translated string for *key* in the current UI language."""
    lang = st.session_state.get("lang", "zh")
    entry = TEXTS.get(key)
    if entry is None:
        return key  # graceful fallback: return the key itself
    return entry.get(lang, entry.get("zh", key))
