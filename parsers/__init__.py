"""Document parsers package for WebAssetify."""

from parsers.universal import extract_urls, is_image_url, is_video_url, classify_urls
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.docx_parser import extract_urls_from_docx

__all__ = [
    "extract_urls",
    "is_image_url",
    "is_video_url",
    "classify_urls",
    "extract_urls_from_pdf",
    "extract_urls_from_docx",
]
