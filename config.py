"""
Global configuration: paths, constants, deployment mode.
Set DEPLOY_MODE=cloud (env var) to disable filesystem storage and LinkedIn automation.
"""
import sys
import os
from pathlib import Path

# ── Deployment mode ───────────────────────────────────────────────────────────
# cloud = session-only storage (no shared filesystem); local = full features
IS_CLOUD: bool = os.getenv("DEPLOY_MODE", "local").lower() == "cloud"

# ── Project layout ────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).parent

OUTPUT_DIR       = PROJECT_ROOT / "output"        # AI read+write
MATERIALS_DIR    = PROJECT_ROOT / "materials"     # AI read-only
CONVERSATIONS_DIR      = PROJECT_ROOT / "conversations"
SETTINGS_FILE          = PROJECT_ROOT / "settings.json"
LINKEDIN_COOKIES_FILE  = PROJECT_ROOT / "linkedin_session.json"
APPLICATIONS_LOG_FILE  = PROJECT_ROOT / "applications_log.json"

# The single "interactive" resume file maintained by the AI
DEFAULT_RESUME_FILENAME = "my_resume.md"

# ── File type sets ────────────────────────────────────────────────────────────
PARSEABLE_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".md"}
IMAGE_EXTENSIONS     = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
ALL_PREVIEW_EXT      = PARSEABLE_EXTENSIONS | IMAGE_EXTENSIONS

# ── Create directories on import (local mode only) ────────────────────────────
if not IS_CLOUD:
    for _d in [OUTPUT_DIR, MATERIALS_DIR, CONVERSATIONS_DIR]:
        _d.mkdir(parents=True, exist_ok=True)

# ── stdout/stderr UTF-8 (Windows) ────────────────────────────────────────────
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
