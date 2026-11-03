import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pymupdf as fitz

from app.modules.agreements.models import AgreementVersion, DocumentPage, utcnow


class InvalidPDF(ValueError):
    pass


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_and_store_pdf(data: bytes, filename: str, storage_dir: Path, max_pages: int) -> tuple[str, int]:
    if not data.startswith(b"%PDF-"):
        raise InvalidPDF("The uploaded file is not a valid PDF.")
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.is_encrypted:
            raise InvalidPDF("Encrypted PDFs are not supported.")
        pages = len(document)
        if pages == 0:
            raise InvalidPDF("The PDF contains no pages.")
        if pages > max_pages:
            raise InvalidPDF(f"PDF exceeds the {max_pages}-page limit.")
        document.close()
    except InvalidPDF:
        raise
    except Exception as exc:
        raise InvalidPDF("The uploaded PDF could not be opened.") from exc

    storage_dir.mkdir(parents=True, exist_ok=True)
    key = f"{uuid4()}.pdf"
    path = storage_dir / key
    path.write_bytes(data)
    return key, pages


def process_version(db, version: AgreementVersion, file_path: Path, max_pages: int) -> list[DocumentPage]:
    try:
        document = fitz.open(file_path)
        if document.is_encrypted or len(document) > max_pages:
            raise InvalidPDF("PDF is encrypted or exceeds the page limit.")
        pages: list[DocumentPage] = []
        for index, page in enumerate(document, start=1):
            text = page.get_text("text")
            warnings = ["No selectable text found; OCR is not enabled."] if not text.strip() else []
            pages.append(DocumentPage(
                agreement_version_id=version.id,
                page_number=index,
                text=text,
                extraction_method="pymupdf_text",
                warnings=json.dumps(warnings),
                text_sha256=sha256_text(text),
            ))
        document.close()
    except InvalidPDF:
        raise
    except Exception as exc:
        raise InvalidPDF("The stored PDF could not be processed.") from exc

    # Replace pages in a single transaction; retries cannot create duplicates.
    for prior in list(version.pages):
        db.delete(prior)
    # Ensure unique (version, page) keys are released before replacement rows insert.
    db.flush()
    db.add_all(pages)
    version.page_count = len(pages)
    version.status = "processed"
    version.processed_at = utcnow()
    return pages
