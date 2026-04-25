"""
Conversation storage: session_state (primary) + optional disk write-through (local mode).
- CLOUD: memory only — per-user isolation.
- LOCAL: also writes JSON files so conversations survive page refreshes.
"""
import json
from datetime import datetime
from typing import Optional


# ── Disk helpers ──────────────────────────────────────────────────────────────

def _conv_path(conv_id: str):
    from config import IS_CLOUD, CONVERSATIONS_DIR
    if IS_CLOUD:
        return None
    return CONVERSATIONS_DIR / f"{conv_id}.json"


def _write_conv(data: dict) -> None:
    path = _conv_path(data["id"])
    if path is None:
        return
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _delete_conv_file(conv_id: str) -> None:
    path = _conv_path(conv_id)
    if path and path.exists():
        try:
            path.unlink()
        except Exception:
            pass


# ── In-memory store (session_state) ──────────────────────────────────────────

class ConversationStore:
    """CRUD for conversation history.  Backed by st.session_state; also writes
    to disk in local mode so that page-refresh restores previous conversations."""

    @property
    def _db(self) -> dict:
        from storage.session_store import _ns
        return _ns("_conversations_db")

    # ── List / load / save ────────────────────────────────────────────────────

    def list_conversations(self) -> list[dict]:
        entries = [
            {
                "id":         d["id"],
                "title":      d.get("title", "新对话"),
                "created_at": d.get("created_at", ""),
                "updated_at": d.get("updated_at", ""),
            }
            for d in self._db.values()
        ]
        return sorted(entries, key=lambda x: x["updated_at"], reverse=True)

    def new_conversation(self) -> dict:
        conv_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        now = datetime.now().isoformat()
        data = {
            "id":         conv_id,
            "title":      "新对话",
            "created_at": now,
            "updated_at": now,
            "messages":   [],
            "session_state": {
                "workflow_stage":          "discovery",
                "selected_job":            None,
                "latest_ranked_jobs_json": "",
                "last_agent_output":       "",
                "resume_source":           None,
            },
        }
        self._db[conv_id] = data
        _write_conv(data)
        return data

    def load_conversation(self, conv_id: str) -> Optional[dict]:
        return self._db.get(conv_id)

    def save_conversation(self, data: dict) -> None:
        data["updated_at"] = datetime.now().isoformat()
        self._db[data["id"]] = data
        _write_conv(data)

    def delete_conversation(self, conv_id: str) -> None:
        self._db.pop(conv_id, None)
        _delete_conv_file(conv_id)

    def rename_conversation(self, conv_id: str, new_title: str) -> None:
        if conv_id in self._db:
            self._db[conv_id]["title"] = new_title
            self._db[conv_id]["updated_at"] = datetime.now().isoformat()
            _write_conv(self._db[conv_id])

    # ── Granular helpers ──────────────────────────────────────────────────────

    def add_message(self, conv_id: str, role: str, content: str) -> None:
        if conv_id not in self._db:
            return
        data = self._db[conv_id]
        data["messages"].append({
            "role":      role,
            "content":   content,
            "timestamp": datetime.now().isoformat(),
        })
        user_msgs = [m for m in data["messages"] if m["role"] == "user"]
        if len(user_msgs) == 1:
            data["title"] = content[:30] + ("…" if len(content) > 30 else "")
        data["updated_at"] = datetime.now().isoformat()
        _write_conv(data)

    def update_session_state(self, conv_id: str, updates: dict) -> None:
        if conv_id in self._db:
            self._db[conv_id].setdefault("session_state", {}).update(updates)
            self._db[conv_id]["updated_at"] = datetime.now().isoformat()
            _write_conv(self._db[conv_id])
