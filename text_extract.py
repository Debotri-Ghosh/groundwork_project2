"""
Text extraction helpers for uploaded documents (PDF / DOCX / TXT).
Used by the POST /upload endpoint in main.py.
"""
import io

import pdfplumber
from docx import Document as DocxDocument


def extract_text(filename: str, data: bytes) -> str:
    """Extract raw text from an uploaded file's bytes.

    Raises ValueError for unsupported extensions or empty documents.
    """
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        text = _extract_pdf(data)
    elif name.endswith(".docx"):
        text = _extract_docx(data)
    elif name.endswith(".txt"):
        text = data.decode("utf-8", errors="ignore")
    else:
        raise ValueError(
            f"Unsupported file type: {filename}. Allowed: .pdf, .docx, .txt"
        )

    if not text or not text.strip():
        raise ValueError(f"No extractable text found in {filename}.")

    return text


def _extract_pdf(data: bytes) -> str:
    pages = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                pages.append(page_text)
    return "\n\n".join(pages)


def _extract_docx(data: bytes) -> str:
    doc = DocxDocument(io.BytesIO(data))
    paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
    return "\n\n".join(paragraphs)
