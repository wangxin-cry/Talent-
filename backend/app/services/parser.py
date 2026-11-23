"""
文档解析：PDF / DOCX → 纯文本

PDF 采用 pdfplumber 优先、PyMuPDF 降级的双引擎；
扫描件 PDF 可渲染成图片交给视觉模型（见 candidates._extract_content）。
"""
from __future__ import annotations

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from loguru import logger

MIN_TEXT_CHARS = 20
MAX_TEXT_CHARS = 200_000
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


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


def _docx_paragraphs(xml_bytes: bytes) -> list[str]:
    """按段落提取一个 Word XML 部件里的全部文本（含文本框）"""
    paragraphs: list[str] = []
    buffer: list[str] = []
    depth = 0
    try:
        for event, elem in ET.iterparse(io.BytesIO(xml_bytes), events=("start", "end")):
            if elem.tag == f"{_W}p":
                if event == "start":
                    depth += 1
                else:
                    depth -= 1
                    if depth == 0:
                        line = "".join(buffer).strip()
                        if line:
                            paragraphs.append(line)
                        buffer = []
                    elem.clear()
            elif event == "end" and elem.tag == f"{_W}t":
                if elem.text:
                    buffer.append(elem.text)
            elif event == "end" and elem.tag in (f"{_W}tab", f"{_W}br", f"{_W}cr"):
                buffer.append(" ")
    except ET.ParseError as exc:
        logger.warning(f"DOCX XML 解析失败：{exc}")
    return paragraphs


def _docx_xml_text(data: bytes) -> str:
    """
    读取 DOCX 全部 XML 文本。

    很多 Word 简历用文本框/页眉排版，python-docx 只能读到空段落；
    直接遍历 w:t 可以把文本框里的正文也取出来。
    """
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            targets = [name for name in ("word/document.xml",) if name in names]
            targets += sorted(name for name in names if re.fullmatch(r"word/header\d+\.xml", name))
            targets += sorted(name for name in names if re.fullmatch(r"word/footer\d+\.xml", name))
            targets += [
                name
                for name in ("word/footnotes.xml", "word/endnotes.xml")
                if name in names
            ]

            paragraphs: list[str] = []
            for name in targets:
                try:
                    paragraphs.extend(_docx_paragraphs(archive.read(name)))
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"DOCX 部件解析失败 {name}：{exc}")
    except zipfile.BadZipFile:
        return ""

    seen: set[str] = set()
    lines: list[str] = []
    for paragraph in paragraphs:
        line = " ".join(paragraph.split())
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


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

    body_text = "\n".join(parts).strip()
    xml_text = _docx_xml_text(data)

    # 文本框/页眉内容明显更多时以 XML 文本为准；普通 DOCX 仍保留表格分隔符
    if len(xml_text) > max(MIN_TEXT_CHARS, int(len(body_text) * 1.15)):
        text, parser = xml_text, "docx-xml"
    else:
        text, parser = body_text, "python-docx"

    if not text:
        raise ParseError("DOCX 中未提取到文字（可能是图片版简历），请上传 PDF 或手动录入")

    return ensure_quality(text), parser, {
        "engine": parser,
        "paragraphs": len(document.paragraphs),
        "tables": len(document.tables),
        "xml_chars": len(xml_text),
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
