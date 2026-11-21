"""
文档解析：PDF / DOCX → 纯文本

PDF 采用 pdfplumber 优先、PyMuPDF 降级的双引擎；
扫描件 PDF 可渲染成图片交给视觉模型（见 candidates._extract_content）。
"""
from __future__ import annotations

import io

from loguru import logger

MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 200_000


class ParseError(RuntimeError):
    """文件无法解析；message 可直接展示给用户"""


def _clean(text: str) -> str:
    return (text or "").replace("\x00", " ").strip()[:MAX_TEXT_CHARS]


def ensure_quality(text: str) -> str:
    """文本质量兜底：空、过短、乱码一律转成可展示的 ParseError（不抛 500）"""
    cleaned = _clean(text)
    if not cleaned:
        raise ParseError("未能从文件中提取到有效文本（可能是扫描件或已损坏），请手动录入")
    bad = cleaned.count("\ufffd")
    if bad / max(len(cleaned), 1) > 0.05:
        raise ParseError("文件内容疑似乱码，请手动录入")
    if len(cleaned) < MIN_TEXT_CHARS:
        raise ParseError("解析出的文本过短，无法识别为简历，请手动录入")
    return cleaned


def extract_text(data: bytes, ext: str) -> tuple[str, str, dict]:
    """同步解析，返回 (文本, 解析器名, 元信息)"""
    if ext == ".pdf":
        return _pdf(data)
    if ext == ".docx":
        return _docx(data)
    if ext == ".doc":
        raise ParseError("暂不支持 .doc 旧格式，请另存为 .docx 后重新上传")
    raise ParseError("暂不支持的简历格式，请上传 PDF / DOCX / 图片")


def _pdf(data: bytes) -> tuple[str, str, dict]:
    parts: list[str] = []
    pages = 0
    try:
        import pdfplumber

        with pdfplumber.open(io.BytesIO(data)) as pdf:
            pages = len(pdf.pages)
            for page in pdf.pages:
                parts.append(page.extract_text() or "")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"pdfplumber 解析失败，尝试 PyMuPDF：{exc}")

    raw = "\n".join(parts).strip()
    if len(raw) >= MIN_TEXT_CHARS:
        return ensure_quality(raw), "pdfplumber", {"engine": "pdfplumber", "pages": pages}

    text, fitz_pages = _pdf_fitz(data)
    if len(text) >= MIN_TEXT_CHARS:
        return ensure_quality(text), "pymupdf", {"engine": "pymupdf", "pages": fitz_pages or pages}
    raise ParseError("PDF 中未提取到文字（可能是扫描件），请上传清晰的图片或手动录入")


def _pdf_fitz(data: bytes) -> tuple[str, int]:
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF 未安装，跳过 PDF 降级解析")
        return "", 0
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            return "\n".join(page.get_text("text") for page in doc).strip(), doc.page_count
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"PyMuPDF 解析失败：{exc}")
        return "", 0


def _docx(data: bytes) -> tuple[str, str, dict]:
    try:
        from docx import Document
    except ImportError as exc:
        raise ParseError("服务端缺少 python-docx，无法解析 DOCX") from exc

    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise ParseError("DOCX 文件已损坏或格式不正确，请重新导出后上传，或手动录入") from exc

    parts = [p.text.strip() for p in document.paragraphs if p.text and p.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text and cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return ensure_quality("\n".join(parts)), "python-docx", {
        "engine": "python-docx",
        "paragraphs": len(document.paragraphs),
        "tables": len(document.tables),
    }


def render_pdf_images(data: bytes, max_pages: int = 3, dpi: int = 150) -> list[bytes]:
    """把 PDF 前几页渲染成 PNG，供扫描件走视觉模型"""
    try:
        import fitz
    except ImportError:
        return []

    images: list[bytes] = []
    try:
        doc = fitz.open(stream=data, filetype="pdf")
        try:
            for index in range(min(max_pages, doc.page_count)):
                pix = doc.load_page(index).get_pixmap(dpi=dpi)
                images.append(pix.tobytes("png"))
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"PDF 渲染图片失败：{exc}")
        return []
    return images
