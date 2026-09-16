"""Document parsers package for WebAssetify."""

from parsers.universal import (
    extract_urls,
    is_image_url,
    is_video_url,
    classify_urls,
    extract_urls_from_tabular,
    extract_urls_from_json,
)
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.docx_parser import extract_urls_from_docx
from parsers.html_parser import extract_urls_from_html
from parsers.security import is_safe_url

__all__ = [
    "extract_urls",
    "is_image_url",
    "is_video_url",
    "classify_urls",
    "extract_urls_from_tabular",
    "extract_urls_from_json",
    "extract_urls_from_pdf",
    "extract_urls_from_docx",
    "extract_urls_from_html",
    "is_safe_url",
]
