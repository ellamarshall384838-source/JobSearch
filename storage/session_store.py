"""
Session-based storage with optional write-through to disk (local mode).
- CLOUD mode (DEPLOY_MODE=cloud): session_state only — no shared filesystem.
- LOCAL mode (default): session_state + write-through to output/ and materials/
  so files survive page refreshes. _seed_from_disk() in app.py restores them.
"""
import streamlit as st
from typing import Optional


# ── Disk write-through helpers (local mode only) ──────────────────────────────

def _disk_write(subdir: str, name: str, data: bytes) -> None:
    try:
        from config import IS_CLOUD, PROJECT_ROOT
        if IS_CLOUD:
            return
        path = PROJECT_ROOT / subdir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    except Exception:
        pass


def _disk_delete(subdir: str, name: str) -> None:
    try:
        from config import IS_CLOUD, PROJECT_ROOT
        if IS_CLOUD:
            return
        path = PROJECT_ROOT / subdir / name
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _disk_rename(subdir: str, old: str, new: str) -> None:
    try:
        from config import IS_CLOUD, PROJECT_ROOT
        if IS_CLOUD:
            return
        src = PROJECT_ROOT / subdir / old
        dst = PROJECT_ROOT / subdir / new
        if src.exists():
            src.rename(dst)
    except Exception:
        pass


# ── Cloud-mode global store (survives page refresh via ?sid= URL param) ───────
#
# Each user gets a random 8-char sid on first visit.
# The sid lives in the URL (?sid=abc12345) so it survives refresh.
# Data lives here on the server for the lifetime of the process.
# No external database required.

import threading
import uuid

_CLOUD_STORE: dict[str, dict] = {}   # {sid: {key: dict}}
_cloud_lock = threading.Lock()
_MAX_SESSIONS = 200   # evict oldest when limit reached


def _cloud_sid() -> str:
    """Return this user's session ID, creating and pinning it to the URL if new."""
    sid = st.query_params.get("sid", "")
    if not sid:
        sid = uuid.uuid4().hex[:8]
        st.query_params["sid"] = sid   # pins sid in URL; triggers one extra rerun
    return sid


def _cloud_ns(key: str) -> dict:
    sid = _cloud_sid()
    with _cloud_lock:
        if len(_CLOUD_STORE) >= _MAX_SESSIONS and sid not in _CLOUD_STORE:
            # Evict oldest entry to cap memory usage
            oldest = next(iter(_CLOUD_STORE))
            del _CLOUD_STORE[oldest]
        store = _CLOUD_STORE.setdefault(sid, {})
        return store.setdefault(key, {})


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ns(key: str) -> dict:
    """Return the namespace dict for *key*, routing to cloud or local store."""
    from config import IS_CLOUD
    if IS_CLOUD:
        return _cloud_ns(key)
    if key not in st.session_state:
        st.session_state[key] = {}
    return st.session_state[key]


# ── Output files (AI-generated: .md, .pdf, …) ────────────────────────────────

def get_output_files() -> dict[str, bytes]:
    return _ns("_output_files")

def save_output_file(name: str, data: "bytes | str") -> None:
    if isinstance(data, str):
        data = data.encode("utf-8")
    _ns("_output_files")[name] = data
    _disk_write("output", name, data)

def get_output_file(name: str) -> Optional[bytes]:
    return _ns("_output_files").get(name)

def delete_output_file(name: str) -> None:
    _ns("_output_files").pop(name, None)
    _disk_delete("output", name)

def rename_output_file(old_name: str, new_name: str) -> None:
    files = _ns("_output_files")
    if old_name in files:
        files[new_name] = files.pop(old_name)
        _disk_rename("output", old_name, new_name)


# ── Material files (user-uploaded: résumés, certs, …) ────────────────────────

def get_materials() -> dict[str, bytes]:
    return _ns("_materials")

def save_material(name: str, data: bytes) -> None:
    _ns("_materials")[name] = data
    _disk_write("materials", name, data)

def get_material(name: str) -> Optional[bytes]:
    return _ns("_materials").get(name)

def delete_material(name: str) -> None:
    _ns("_materials").pop(name, None)
    _disk_delete("materials", name)


# ── Interactive (AI-maintained) résumé ───────────────────────────────────────

def _scalar_store() -> dict:
    """Single dict that holds all non-namespace scalar values."""
    return _ns("_scalars")

def get_interactive_resume() -> str:
    return _scalar_store().get("resume", "")

def save_interactive_resume(content: str) -> None:
    _scalar_store()["resume"] = content
    _disk_write("output", "my_resume.md", content.encode("utf-8"))


# ── App settings (API key, model, LinkedIn credentials) ──────────────────────

_SETTING_DEFAULTS = {
    "api_key":           "",
    "base_url":          "https://generativelanguage.googleapis.com/v1beta/openai/",
    "model":             "gemini-2.5-flash",
    "linkedin_email":    "",
    "linkedin_password": "",
}

def get_settings() -> dict:
    """Return current settings, falling back to env vars then defaults."""
    import os
    saved: dict = _scalar_store().get("app_settings", {})
    return {
        "api_key":           saved.get("api_key")  or os.getenv("OPENAI_API_KEY", ""),
        "base_url":          saved.get("base_url") or os.getenv("OPENAI_BASE_URL", _SETTING_DEFAULTS["base_url"]),
        "model":             saved.get("model")    or os.getenv("OPENAI_MODEL",    _SETTING_DEFAULTS["model"]),
        "linkedin_email":    saved.get("linkedin_email",    ""),
        "linkedin_password": saved.get("linkedin_password", ""),
    }

def save_settings(
    api_key: str,
    base_url: str,
    model: str,
    linkedin_email: str = "",
    linkedin_password: str = "",
) -> None:
    _scalar_store()["app_settings"] = {
        "api_key":           api_key,
        "base_url":          base_url,
        "model":             model,
        "linkedin_email":    linkedin_email,
        "linkedin_password": linkedin_password,
    }


# ── LinkedIn session cookies ──────────────────────────────────────────────────
# Stored via _scalar_store() so they survive page refresh in both local and
# cloud modes (cloud uses _CLOUD_STORE keyed by URL ?sid=).

def get_linkedin_cookies() -> Optional[list]:
    return _scalar_store().get("linkedin_cookies")

def save_linkedin_cookies(cookies: list) -> None:
    _scalar_store()["linkedin_cookies"] = cookies

def clear_linkedin_cookies() -> None:
    _scalar_store().pop("linkedin_cookies", None)
    _scalar_store().pop("linkedin_storage_state", None)

def has_linkedin_session() -> bool:
    return bool(_scalar_store().get("linkedin_cookies"))


# ── LinkedIn Playwright storage state (cookies + localStorage) ────────────────
# Richer than cookies alone; required for LinkedIn to pass bot-detection.
# Stored as a JSON string so it survives page refresh in both local and cloud.

def get_linkedin_storage_state() -> Optional[str]:
    return _scalar_store().get("linkedin_storage_state")

def save_linkedin_storage_state(state_json: str) -> None:
    _scalar_store()["linkedin_storage_state"] = state_json


# ── User profile (nationality, visa, phone, etc.) ────────────────────────────
# Isolated per user in cloud mode (different ?sid= per user).
# Persisted to output/user_profile.json in local mode.

def get_user_profile() -> dict:
    return _scalar_store().get("user_profile", {})

def save_user_profile(profile: dict) -> None:
    _scalar_store()["user_profile"] = profile
