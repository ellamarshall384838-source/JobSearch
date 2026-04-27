"""
Persistent user profile for form-filling and personalisation.

Stored in output/user_profile.json (local mode) and in session_store (all modes).
The profile is separate from the resume so it survives resume rewrites and
can be updated independently when users provide personal info.
"""
import json
from pathlib import Path
from config import PROJECT_ROOT

PROFILE_FILE = PROJECT_ROOT / "output" / "user_profile.json"

# Fields the agent will maintain.  Keys match common Easy Apply question topics.
_DEFAULTS: dict = {
    "full_name":        "",
    "phone":            "",
    "email":            "",
    "city":             "Singapore",
    "nationality":      "",          # e.g. "Chinese", "Indian"
    "work_authorization": "",        # e.g. "Singapore EP", "PR", "Citizen", "DP"
    "years_experience": "",          # e.g. "3"
    "expected_salary":  "Negotiable",
    "linkedin_url":     "",
    "github_url":       "",
    "notes":            "",          # free-form extra info
}

_FIELD_LABELS = {
    "full_name":          "姓名",
    "phone":              "电话",
    "email":              "邮箱",
    "city":               "城市",
    "nationality":        "国籍",
    "work_authorization": "工作身份/签证类型",
    "years_experience":   "相关工作年限",
    "expected_salary":    "期望薪资",
    "linkedin_url":       "LinkedIn 主页",
    "github_url":         "GitHub 主页",
    "notes":              "其他备注",
}


def get_profile() -> dict:
    """Return current user profile (session → disk → defaults)."""
    try:
        from storage.session_store import get_user_profile
        profile = get_user_profile()
        if profile:
            return profile
    except Exception:
        pass
    # Disk fallback (local mode, after page refresh)
    if PROFILE_FILE.exists():
        try:
            data = json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
            _sync_to_session(data)
            return data
        except Exception:
            pass
    return dict(_DEFAULTS)


def save_profile(updates: dict) -> dict:
    """Merge *updates* into the existing profile and persist.  Returns the new profile."""
    profile = get_profile()
    for k, v in updates.items():
        if k in _DEFAULTS and str(v).strip():
            profile[k] = str(v).strip()
    _sync_to_session(profile)
    try:
        PROFILE_FILE.parent.mkdir(exist_ok=True)
        PROFILE_FILE.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass
    return profile


def profile_to_text(profile: dict | None = None) -> str:
    """Return a human-readable summary of the profile for agent prompts."""
    if profile is None:
        profile = get_profile()
    lines = []
    for key, label in _FIELD_LABELS.items():
        val = profile.get(key, "").strip()
        if val:
            lines.append(f"  {label}: {val}")
    return "【用户个人档案】\n" + "\n".join(lines) if lines else "（暂无用户档案，建议先告知国籍/签证状态等信息）"


def _sync_to_session(profile: dict) -> None:
    try:
        from storage.session_store import save_user_profile
        save_user_profile(profile)
    except Exception:
        pass
