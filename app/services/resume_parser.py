"""
Resume Parser Service
Supports: PDF, DOCX, DOC
Returns cleaned plain text for downstream processing.
"""
import os
import io
from pathlib import Path
from typing import Union

from app.core.exceptions import ResumeParseError
from app.core.logger import get_logger

log = get_logger(__name__)


def parse_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF file using PyMuPDF."""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        texts = [page.get_text("text") for page in doc]
        doc.close()
        return "\n".join(texts).strip()
    except Exception as e:
        raise ResumeParseError(f"PDF parsing failed: {e}")


def parse_docx(file_bytes: bytes) -> str:
    """Extract text from a DOCX file."""
    try:
        from docx import Document
        doc = Document(io.BytesIO(file_bytes))
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n".join(paragraphs).strip()
    except Exception as e:
        raise ResumeParseError(f"DOCX parsing failed: {e}")


def parse_resume(file_bytes: bytes, filename: str) -> str:
    """
    Auto-detect file type and extract text.
    Supported: .pdf, .docx, .doc, .txt
    """
    ext = Path(filename).suffix.lower()
    log.info(f"Parsing resume: {filename} ({ext})")

    if ext == ".pdf":
        return parse_pdf(file_bytes)
    elif ext in (".docx", ".doc"):
        return parse_docx(file_bytes)
    elif ext == ".txt":
        return file_bytes.decode("utf-8", errors="ignore").strip()
    else:
        raise ResumeParseError(f"Unsupported file format: {ext}")


async def save_resume_file(file_bytes: bytes, filename: str, upload_dir: str) -> str:
    """Persist uploaded resume to disk and return the saved path."""
    os.makedirs(upload_dir, exist_ok=True)
    save_path = os.path.join(upload_dir, filename)
    with open(save_path, "wb") as f:
        f.write(file_bytes)
    log.info(f"Resume saved: {save_path}")
    return save_path
