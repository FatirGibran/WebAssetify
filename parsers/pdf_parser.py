"""PDF Document parser for WebAssetify.

Extracts visible text and clickable /URI link annotations from PDF documents
using pypdf.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import BinaryIO, Union

import pypdf

from parsers.universal import clean_url, extract_urls

logger = logging.getLogger(__name__)


def extract_urls_from_pdf(source: Union[str, Path, bytes, BinaryIO]) -> list[str]:
    """Extract URLs from a PDF document (visible text and hyperlink annotations).

    Args:
        source: File path, Path object, raw bytes, or file-like binary stream.

    Returns:
        Deduplicated list of extracted URLs.
    """
    stream: BinaryIO
    if isinstance(source, (str, Path)):
        file_path = Path(source)
        if not file_path.exists():
            logger.error("PDF file does not exist: %s", source)
            return []
        stream = io.BytesIO(file_path.read_bytes())
    elif isinstance(source, bytes):
        stream = io.BytesIO(source)
    else:
        stream = source

    urls: list[str] = []

    try:
        reader = pypdf.PdfReader(stream)

        for page_idx, page in enumerate(reader.pages):
            # 1. Extract URLs from visible text
            try:
                page_text = page.extract_text() or ""
                if page_text:
                    urls.extend(extract_urls(page_text))
            except Exception as e:
                logger.warning("Failed to extract text from page %d: %s", page_idx, e)

            # 2. Extract URLs from /Annots (clickable hyperlinks)
            try:
                annots = page.get("/Annots")
                if annots:
                    # In pypdf, resolve if it's an indirect object
                    annots_obj = annots.get_object() if hasattr(annots, "get_object") else annots
                    if isinstance(annots_obj, list):
                        for annot_ref in annots_obj:
                            annot = (
                                annot_ref.get_object()
                                if hasattr(annot_ref, "get_object")
                                else annot_ref
                            )
                            if not isinstance(annot, dict):
                                continue

                            # Check for Action dictionary (/A)
                            action = annot.get("/A")
                            if action:
                                action_obj = (
                                    action.get_object()
                                    if hasattr(action, "get_object")
                                    else action
                                )
                                if isinstance(action_obj, dict):
                                    uri = action_obj.get("/URI")
                                    if uri:
                                        cleaned = clean_url(str(uri))
                                        if cleaned:
                                            urls.append(cleaned)

                            # Direct /URI field on annotation
                            direct_uri = annot.get("/URI")
                            if direct_uri:
                                cleaned = clean_url(str(direct_uri))
                                if cleaned:
                                    urls.append(cleaned)
            except Exception as e:
                logger.warning(
                    "Failed to extract annotations from page %d: %s", page_idx, e
                )

    except Exception as e:
        logger.error("Error reading PDF stream: %s", e)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped
