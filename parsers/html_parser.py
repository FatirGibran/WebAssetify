"""HTML Document parser for WebAssetify.

Extracts media links, video/audio sources, image URLs (including srcset and data-src),
and hyperlinks from HTML documents using Python's standard library html.parser.
"""

from __future__ import annotations

import io
import logging
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import BinaryIO, Union

from parsers.universal import clean_url, extract_urls

logger = logging.getLogger(__name__)

# Pattern to extract urls inside CSS url(...) syntax
CSS_URL_PATTERN = re.compile(
    r'url\(\s*[\'"]?\s*(https?://[^\'")\s]+)\s*[\'"]?\s*\)',
    re.IGNORECASE,
)


class _MediaHTMLParser(HTMLParser):
    """Internal HTML parser to extract resource URLs and hyperlinks."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.extracted_urls: list[str] = []
        self._in_style_block = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "").strip() for k, v in attrs}

        if tag_lower == "style":
            self._in_style_block = True

        # Check inline styles for background-image: url(...)
        inline_style = attr_dict.get("style")
        if inline_style:
            for match in CSS_URL_PATTERN.finditer(inline_style):
                cleaned = clean_url(match.group(1))
                if cleaned:
                    self.extracted_urls.append(cleaned)

        # <a> and <link> href
        if tag_lower in ("a", "link"):
            href = attr_dict.get("href")
            if href and (href.startswith("http://") or href.startswith("https://")):
                cleaned = clean_url(href)
                if cleaned:
                    self.extracted_urls.append(cleaned)

        # <img> src, data-src, srcset
        elif tag_lower == "img":
            for key in ("src", "data-src", "data-original"):
                val = attr_dict.get(key)
                if val and (val.startswith("http://") or val.startswith("https://")):
                    cleaned = clean_url(val)
                    if cleaned:
                        self.extracted_urls.append(cleaned)

            srcset = attr_dict.get("srcset")
            if srcset:
                self._parse_srcset(srcset)

        # <video>, <audio>, <iframe> src
        elif tag_lower in ("video", "audio", "iframe"):
            src = attr_dict.get("src")
            if src and (src.startswith("http://") or src.startswith("https://")):
                cleaned = clean_url(src)
                if cleaned:
                    self.extracted_urls.append(cleaned)

            poster = attr_dict.get("poster")
            if poster and (poster.startswith("http://") or poster.startswith("https://")):
                cleaned = clean_url(poster)
                if cleaned:
                    self.extracted_urls.append(cleaned)

        # <source> src and srcset
        elif tag_lower == "source":
            src = attr_dict.get("src")
            if src and (src.startswith("http://") or src.startswith("https://")):
                cleaned = clean_url(src)
                if cleaned:
                    self.extracted_urls.append(cleaned)

            srcset = attr_dict.get("srcset")
            if srcset:
                self._parse_srcset(srcset)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "style":
            self._in_style_block = False

    def handle_data(self, data: str) -> None:
        if self._in_style_block:
            for match in CSS_URL_PATTERN.finditer(data):
                cleaned = clean_url(match.group(1))
                if cleaned:
                    self.extracted_urls.append(cleaned)
        else:
            # Check text body for standalone URLs
            if "http://" in data or "https://" in data:
                found = extract_urls(data)
                self.extracted_urls.extend(found)

    def _parse_srcset(self, srcset_val: str) -> None:
        """Parse srcset attribute containing candidate URLs."""
        parts = srcset_val.split(",")
        for part in parts:
            part = part.strip()
            if not part:
                continue
            tokens = part.split()
            if tokens:
                candidate = tokens[0]
                if candidate.startswith("http://") or candidate.startswith("https://"):
                    cleaned = clean_url(candidate)
                    if cleaned:
                        self.extracted_urls.append(cleaned)


def extract_urls_from_html(source: Union[str, Path, bytes, BinaryIO]) -> list[str]:
    """Extract all media and hyperlink URLs from an HTML document.

    Args:
        source: HTML string, file path, bytes, or binary stream.

    Returns:
        Deduplicated list of extracted URLs.
    """
    html_text: str
    if isinstance(source, (str, Path)) and (isinstance(source, Path) or (Path(source).is_file() and "\n" not in str(source))):
        file_path = Path(source)
        if not file_path.exists():
            logger.error("HTML file does not exist: %s", source)
            return []
        try:
            html_text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            logger.error("Failed to read HTML file %s: %s", source, e)
            return []
    elif isinstance(source, bytes):
        html_text = source.decode("utf-8", errors="replace")
    elif hasattr(source, "read"):
        raw = source.read()
        if isinstance(raw, bytes):
            html_text = raw.decode("utf-8", errors="replace")
        else:
            html_text = str(raw)
    else:
        html_text = str(source)

    parser = _MediaHTMLParser()
    try:
        parser.feed(html_text)
    except Exception as e:
        logger.warning("HTML parser encountered error: %s, falling back to regex", e)
        return extract_urls(html_text)

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in parser.extracted_urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped
