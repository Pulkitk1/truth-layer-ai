from typing import Literal

from pydantic import BaseModel


class UploadResponse(BaseModel):
    file_id: str
    filename: str
    file_size: int
    upload_status: Literal["uploaded"]
    # Proves ownership of this document. Shown once: only its hash is stored, so it cannot be recovered.
    access_token: str


class ExtractRequest(BaseModel):
    file_id: str


class PageText(BaseModel):
    page_number: int
    extracted_text: str
    char_count: int
    is_empty: bool


class ExtractResponse(BaseModel):
    file_id: str
    filename: str
    total_pages: int
    extraction_status: Literal["success", "partial", "no_text"]
    ocr_required: bool
    empty_pages: list[int]
    extracted_text: str  # full text, non-empty pages joined
    pages: list[PageText]
    message: str | None = None
