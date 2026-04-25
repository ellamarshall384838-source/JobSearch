"""
Multi-format file parser: PDF, DOCX, TXT, MD.
Supports both file-path and in-memory bytes inputs.
"""
import io
from pathlib import Path
from config import PARSEABLE_EXTENSIONS, IMAGE_EXTENSIONS


# ── Path-based API (kept for backward compat) ─────────────────────────────────

def parse_file(file_path) -> str:
    """Parse any supported file at *file_path* and return plain-text content."""
    path = Path(file_path)
    if not path.exists():
        return f"[错误] 文件未找到: {file_path}"
    try:
        data = path.read_bytes()
        return parse_bytes(path.name, data)
    except Exception as e:
        return f"[解析错误] {e}"


# ── Bytes-based API (for in-memory / cloud use) ────────────────────────────────

def parse_bytes(filename: str, data: bytes) -> str:
    """Parse file content from raw bytes given *filename* (used for extension)."""
    ext = Path(filename).suffix.lower()
    try:
        if ext == ".pdf":
            return _parse_pdf_bytes(data)
        elif ext in (".doc", ".docx"):
            return _parse_docx_bytes(data)
        elif ext in (".txt", ".md"):
            return data.decode("utf-8", errors="replace")
        else:
            return f"[不支持的文件类型: {ext}]"
    except Exception as e:
        return f"[解析错误] {e}"


# ── Internal parsers ──────────────────────────────────────────────────────────

def _parse_pdf_bytes(data: bytes) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(p for p in pages if p)
    except ImportError:
        pass
    import PyPDF2
    reader = PyPDF2.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _parse_docx_bytes(data: bytes) -> str:
    import docx
    doc = docx.Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


# ── Utility helpers ───────────────────────────────────────────────────────────

def is_image(file_path) -> bool:
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS

def is_parseable(file_path) -> bool:
    return Path(file_path).suffix.lower() in PARSEABLE_EXTENSIONS

def is_parseable_name(filename: str) -> bool:
    """Check by filename string (no filesystem access needed)."""
    return Path(filename).suffix.lower() in PARSEABLE_EXTENSIONS

def is_image_name(filename: str) -> bool:
    return Path(filename).suffix.lower() in IMAGE_EXTENSIONS
