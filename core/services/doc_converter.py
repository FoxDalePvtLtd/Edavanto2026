"""
Service for converting study documents (DOCX, DOC, TXT, MD) into
interactive, styled web notes for in-browser reading.
"""

from __future__ import annotations

import html
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Optional

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS_MAP = {"w": W_NS}


def convert_docx_to_html(data: bytes) -> str:
    """
    Parses a DOCX binary byte stream into formatted, semantic HTML notes.
    Supports headings, paragraphs, bold, italic, underline, lists, and tables.
    """
    if not data:
        return "<p class='text-muted'><em>Empty document.</em></p>"

    # Check if it's a valid ZIP archive containing word/document.xml
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if "word/document.xml" not in z.namelist():
                return _fallback_text_to_html(data)
            xml_content = z.read("word/document.xml")
    except Exception:
        return _fallback_text_to_html(data)

    try:
        tree = ET.fromstring(xml_content)
    except Exception as exc:
        return f"<div class='alert alert-warning'>Unable to parse document XML: {html.escape(str(exc))}</div>"

    body = tree.find("w:body", NS_MAP)
    if body is None:
        return "<p class='text-muted'><em>Empty document body.</em></p>"

    html_parts: list[str] = []

    def get_run_text_and_format(run) -> str:
        rpr = run.find("w:rPr", NS_MAP)
        is_bold = False
        is_italic = False
        is_underline = False

        if rpr is not None:
            if rpr.find("w:b", NS_MAP) is not None:
                is_bold = True
            if rpr.find("w:i", NS_MAP) is not None:
                is_italic = True
            if rpr.find("w:u", NS_MAP) is not None:
                is_underline = True

        texts: list[str] = []
        for elem in run:
            tag = elem.tag
            if tag == f"{{{W_NS}}}t":
                if elem.text:
                    texts.append(elem.text)
            elif tag == f"{{{W_NS}}}tab":
                texts.append(" &nbsp; &nbsp; ")
            elif tag == f"{{{W_NS}}}br":
                texts.append("<br/>")

        raw_text = "".join(texts)
        if not raw_text:
            return ""

        escaped = html.escape(raw_text)
        escaped = escaped.replace("&lt;br/&gt;", "<br/>")

        if is_bold:
            escaped = f"<strong>{escaped}</strong>"
        if is_italic:
            escaped = f"<em>{escaped}</em>"
        if is_underline:
            escaped = f"<u>{escaped}</u>"

        return escaped

    for child in body:
        tag = child.tag
        if tag == f"{{{W_NS}}}p":
            p = child
            ppr = p.find("w:pPr", NS_MAP)
            style_val = ""
            is_list = False

            if ppr is not None:
                pstyle = ppr.find("w:pStyle", NS_MAP)
                if pstyle is not None:
                    style_val = (pstyle.attrib.get(f"{{{W_NS}}}val") or "").lower()
                numpr = ppr.find("w:numPr", NS_MAP)
                if numpr is not None:
                    is_list = True

            runs_html = [get_run_text_and_format(r) for r in p.findall("w:r", NS_MAP)]
            p_content = "".join(runs_html).strip()
            if not p_content:
                continue

            if "heading1" in style_val or "title" in style_val:
                html_parts.append(
                    f"<h3 class='note-heading-1 mt-4 mb-2 fw-bold text-primary border-bottom pb-2'>{p_content}</h3>"
                )
            elif "heading2" in style_val:
                html_parts.append(
                    f"<h4 class='note-heading-2 mt-3 mb-2 fw-bold text-dark'>{p_content}</h4>"
                )
            elif "heading3" in style_val or "subtitle" in style_val:
                html_parts.append(
                    f"<h5 class='note-heading-3 mt-3 mb-1 fw-semibold text-secondary'>{p_content}</h5>"
                )
            elif is_list or "list" in style_val:
                html_parts.append(
                    f"<li class='note-list-item mb-1 ms-3'>{p_content}</li>"
                )
            else:
                html_parts.append(
                    f"<p class='note-paragraph mb-2 text-dark' style='line-height: 1.7;'>{p_content}</p>"
                )

        elif tag == f"{{{W_NS}}}tbl":
            tbl = child
            tbl_html = [
                "<div class='table-responsive my-3'><table class='table table-bordered table-striped note-table mb-0'>"
            ]
            for tr in tbl.findall("w:tr", NS_MAP):
                tbl_html.append("<tr>")
                for tc in tr.findall("w:tc", NS_MAP):
                    tc_text_parts: list[str] = []
                    for tcp in tc.findall("w:p", NS_MAP):
                        cell_runs = [
                            get_run_text_and_format(r)
                            for r in tcp.findall("w:r", NS_MAP)
                        ]
                        cell_p = "".join(cell_runs).strip()
                        if cell_p:
                            tc_text_parts.append(cell_p)
                    cell_html = "<br/>".join(tc_text_parts) or "&nbsp;"
                    tbl_html.append(f"<td>{cell_html}</td>")
                tbl_html.append("</tr>")
            tbl_html.append("</table></div>")
            html_parts.append("".join(tbl_html))

    if not html_parts:
        return "<p class='text-muted'><em>No readable text content found in document.</em></p>"

    return "\n".join(html_parts)


def _fallback_text_to_html(data: bytes) -> str:
    """
    Fallback extractor for text, markdown, or binary files that contain strings.
    """
    try:
        # Try UTF-8 decoding
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = data.decode("latin-1")
        except Exception:
            # Extract printable ASCII runs of 4+ characters
            matches = re.findall(rb"[\x20-\x7E\t\r\n]{4,}", data)
            text = b"\n\n".join(matches).decode("ascii", errors="replace")

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        # Try single newline split
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    if not paragraphs:
        return "<p class='text-muted'><em>Document preview unavailable.</em></p>"

    out = []
    for p in paragraphs:
        escaped = html.escape(p).replace("\n", "<br/>")
        if p.startswith("# "):
            out.append(f"<h3 class='note-heading-1 mt-4 mb-2 fw-bold text-primary border-bottom pb-2'>{html.escape(p[2:])}</h3>")
        elif p.startswith("## "):
            out.append(f"<h4 class='note-heading-2 mt-3 mb-2 fw-bold text-dark'>{html.escape(p[3:])}</h4>")
        elif p.startswith("### "):
            out.append(f"<h5 class='note-heading-3 mt-3 mb-1 fw-semibold text-secondary'>{html.escape(p[4:])}</h5>")
        elif p.startswith("- ") or p.startswith("* "):
            out.append(f"<li class='note-list-item mb-1 ms-3'>{html.escape(p[2:])}</li>")
        else:
            out.append(f"<p class='note-paragraph mb-2 text-dark' style='line-height: 1.7;'>{escaped}</p>")

    return "\n".join(out)


def convert_material_to_note_html(data: bytes, filename: str = "", material_type: str = "") -> str:
    """
    Converts decrypted bytes of a study material into note HTML based on filename / material_type.
    """
    lower_fname = (filename or "").lower()
    if lower_fname.endswith((".docx", ".dotx")) or material_type == "docx":
        return convert_docx_to_html(data)
    else:
        return _fallback_text_to_html(data)
