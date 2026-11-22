import pymupdf

from . import config
from .schemas import ExtractResponse, PageText


class PdfError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def extract_pdf(data: bytes, file_id: str, filename: str) -> ExtractResponse:
    """Extract the text of a PDF held in memory (it is read straight from the database, never written to disk)."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise PdfError("corrupted_pdf", "This PDF is corrupted or could not be opened.") from exc

    with doc:
        if doc.needs_pass:
            raise PdfError(
                "password_protected",
                "This PDF is password-protected. Remove the password and upload it again.",
            )
        if doc.page_count == 0:
            raise PdfError("empty_pdf", "This PDF contains no pages.")
        if doc.page_count > config.max_pdf_pages():
            raise PdfError(
                "too_many_pages",
                f"This PDF has {doc.page_count} pages; the limit is {config.max_pdf_pages()}. Split it and upload the parts.",
                status=413,
            )

        pages: list[PageText] = []
        has_images = False
        try:
            for i, page in enumerate(doc):
                text = page.get_text("text").strip()
                if not text and page.get_images(full=True):
                    has_images = True
                pages.append(
                    PageText(
                        page_number=i + 1,
                        extracted_text=text,
                        char_count=len(text),
                        is_empty=not text,
                    )
                )
        except Exception as exc:
            raise PdfError(
                "corrupted_pdf", "This PDF is damaged and could not be fully read."
            ) from exc

    empty = [p.page_number for p in pages if p.is_empty]
    if len(empty) == len(pages):
        status, ocr = "no_text", True
        message = (
            "No extractable text found. This looks like a scanned/image-only PDF; OCR is required."
            if has_images
            else "No extractable text found in this PDF (all pages are empty)."
        )
    elif empty:
        status, ocr = "partial", False
        message = f"{len(empty)} of {len(pages)} page(s) contain no extractable text."
    else:
        status, ocr, message = "success", False, None

    return ExtractResponse(
        file_id=file_id,
        filename=filename,
        total_pages=len(pages),
        extraction_status=status,
        ocr_required=ocr,
        empty_pages=empty,
        extracted_text="\n\n".join(p.extracted_text for p in pages if not p.is_empty),
        pages=pages,
        message=message,
    )
