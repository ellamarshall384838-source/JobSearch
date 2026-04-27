"""
Markdown → PDF conversion.

Primary: weasyprint (beautiful CSS output, requires GTK on Windows).
Fallback: fpdf2 with a Unicode-capable system font (works everywhere).
"""
import re
from pathlib import Path
from datetime import datetime


# ── CSS for weasyprint ────────────────────────────────────────────────────────

_RESUME_CSS = """
@page { size: A4; margin: 18mm 20mm; }
body {
    font-family: "Arial", "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC",
                 sans-serif;
    font-size: 10.5pt; line-height: 1.6; color: #1a1a1a;
}
h1 {
    font-size: 22pt; letter-spacing: 1px; border-bottom: 2.5px solid #2c3e50;
    padding-bottom: 5px; margin: 0 0 8px 0; color: #1a252f;
}
h2 {
    font-size: 13pt; color: #2c3e50; border-bottom: 1px solid #bdc3c7;
    padding-bottom: 2px; margin: 14px 0 6px 0;
    text-transform: uppercase; letter-spacing: 0.5px;
}
h3 { font-size: 11pt; color: #34495e; margin: 8px 0 3px 0; }
p  { margin: 3px 0 5px 0; }
ul { margin: 4px 0; padding-left: 18px; }
li { margin-bottom: 2px; }
strong { color: #111; } em { color: #555; }
a { color: #2980b9; text-decoration: none; }
hr { border: none; border-top: 1px solid #bdc3c7; margin: 8px 0; }
table { border-collapse: collapse; width: 100%; margin: 6px 0; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left; }
th { background: #ecf0f1; font-weight: bold; }
"""


# ── Windows font search ───────────────────────────────────────────────────────

_WIN_FONTS = [
    # Windows
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/arial.ttf",
    # Linux (Streamlit Cloud / Docker)
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # macOS
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode MS.ttf",
]


def _find_unicode_font() -> str | None:
    """Return the first available Unicode font path, or None."""
    for p in _WIN_FONTS:
        if Path(p).exists():
            return p
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def md_to_pdf_bytes(md_content: str) -> bytes:
    """
    Convert Markdown *md_content* to PDF and return the raw bytes.
    Tries weasyprint first, then falls back to fpdf2.
    No disk I/O required.
    """
    try:
        return _via_weasyprint_bytes(md_content)
    except Exception as primary_err:
        print(f"[PDFGenerator] weasyprint unavailable ({type(primary_err).__name__}), using fpdf2…")
        return _via_fpdf2_bytes(md_content)


def md_to_pdf(md_content: str, output_path: Path) -> Path:
    """
    Convert Markdown *md_content* to a PDF at *output_path*.
    Kept for backward compatibility; delegates to md_to_pdf_bytes.
    """
    output_path = Path(output_path)
    pdf_bytes = md_to_pdf_bytes(md_content)
    output_path.write_bytes(pdf_bytes)
    return output_path


# ── weasyprint path ───────────────────────────────────────────────────────────

def _html_from_md(md_content: str) -> str:
    import markdown as md_lib
    html_body = md_lib.markdown(
        md_content, extensions=["tables", "fenced_code", "nl2br", "sane_lists"]
    )
    return (
        "<!DOCTYPE html><html lang='zh'><head><meta charset='UTF-8'></head>"
        f"<body>{html_body}</body></html>"
    )


def _via_weasyprint_bytes(md_content: str) -> bytes:
    from weasyprint import HTML, CSS
    return HTML(string=_html_from_md(md_content)).write_pdf(
        stylesheets=[CSS(string=_RESUME_CSS)]
    )


def _via_weasyprint(md_content: str, output_path: Path) -> Path:
    output_path.write_bytes(_via_weasyprint_bytes(md_content))
    return output_path


# ── fpdf2 fallback ────────────────────────────────────────────────────────────

def _via_fpdf2_bytes(md_content: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_margins(20, 18, 20)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)

    # Load a Unicode font (needed for CJK and special chars).
    # For custom TTF fonts fpdf2 cannot synthesise bold, so we differentiate
    # heading levels via font SIZE only; Helvetica can use bold.
    font_name = "Helvetica"
    font_path = _find_unicode_font()
    if font_path:
        try:
            pdf.add_font("UniFont", fname=font_path, uni=True)
            font_name = "UniFont"
            print(f"[PDFGenerator] Using Unicode font: {Path(font_path).name}")
        except Exception as fe:
            print(f"[PDFGenerator] Could not load {font_path}: {fe}")

    use_builtin = (font_name == "Helvetica")   # built-ins support bold/italic

    def _safe(text: str) -> str:
        """Strip inline Markdown marks; sanitise for font encoding."""
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\*(.+?)\*",     r"\1", text)
        text = re.sub(r"`(.+?)`",       r"\1", text)
        text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
        if use_builtin:
            return text.encode("latin-1", errors="replace").decode("latin-1")
        return text

    def _reset_x(extra: float = 0.0):
        """Move cursor back to left margin + optional indent."""
        pdf.set_x(pdf.l_margin + extra)

    def h(level: int, text: str, size: int):
        _reset_x()
        pdf.ln(3 if level > 1 else 0)
        style = "B" if use_builtin else ""
        pdf.set_font(font_name, style, size)
        _reset_x()
        w = pdf.w - pdf.l_margin - pdf.r_margin
        pdf.multi_cell(w, size * 0.5, _safe(text))
        if level <= 2:
            pdf.set_draw_color(44, 62, 80)
            pdf.set_line_width(0.4 if level == 1 else 0.2)
            _reset_x()
            pdf.line(pdf.l_margin, pdf.get_y(),
                     pdf.w - pdf.r_margin, pdf.get_y())
        _reset_x()
        pdf.ln(1)

    def body(text: str, indent: float = 0.0):
        pdf.set_font(font_name, "", 10)
        _reset_x(indent)
        w = pdf.w - pdf.l_margin - pdf.r_margin - indent
        if w > 20:
            pdf.multi_cell(w, 5, _safe(text))
        _reset_x()

    for raw_line in md_content.split("\n"):
        line = raw_line.rstrip()
        if   line.startswith("# "):       h(1, line[2:], 18)
        elif line.startswith("## "):      h(2, line[3:], 12)
        elif line.startswith("### "):     h(3, line[4:], 10)
        elif re.match(r"^[-*+] ", line):  body("- " + line[2:], indent=5)
        elif line.startswith("---"):
            pdf.set_draw_color(189, 195, 199)
            pdf.set_line_width(0.2)
            pdf.line(pdf.get_x(), pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
            pdf.ln(2)
        elif line.strip():
            body(line)
        else:
            pdf.ln(2)

    return bytes(pdf.output())


def _via_fpdf2(md_content: str, output_path: Path) -> Path:
    output_path.write_bytes(_via_fpdf2_bytes(md_content))
    return output_path


# ── Filename helper ───────────────────────────────────────────────────────────

def make_resume_filename(job_title: str = "", company: str = "") -> str:
    parts = [p for p in [job_title, company] if p]
    tag   = "_".join(parts)[:40] if parts else "resume"
    safe  = re.sub(r"[^A-Za-z0-9\u4e00-\u9fff_-]", "_", tag)
    return f"resume_{datetime.now().strftime('%Y%m%d')}_{safe}"
