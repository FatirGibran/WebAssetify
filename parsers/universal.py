"""Universal URL extraction and media classification module.

Handles raw text and Markdown formats ([text](url), ![alt](url))
with deduplication and URL categorization.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

# Regex for Markdown syntax: ![alt](url) and [text](url)
MARKDOWN_LINK_PATTERN = re.compile(
    r'!*\[[^\]]*\]\(\s*(https?://[^\s\)]+)\s*\)',
    re.IGNORECASE,
)

# Regex for standalone raw URLs
RAW_URL_PATTERN = re.compile(
    r'(?:https?://|www\.)[^\s<>"\'{}|\\^`]+',
    re.IGNORECASE,
)

# Known extensions
IMAGE_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".bmp", ".tiff", ".tif", ".ico", ".svg", ".avif",
}

VIDEO_EXTENSIONS = {
    ".mp4", ".webm", ".mov", ".mkv", ".m4v",
    ".avi", ".flv", ".wmv", ".ts",
}

# Known video hostnames / patterns
VIDEO_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "vimeo.com",
    "www.vimeo.com",
    "tiktok.com",
    "www.tiktok.com",
    "dailymotion.com",
    "www.dailymotion.com",
    "twitch.tv",
    "www.twitch.tv",
    "twitter.com",
    "x.com",
}


def clean_url(url: str) -> str:
    """Clean trailing punctuation and normalize scheme."""
    url = url.strip()
    if url.startswith("www."):
        url = "https://" + url

    # Strip unwanted trailing punctuation often picked up at sentence ends
    url = re.sub(r'[\.,;:!?\)\]>"\']+$', '', url)
    return url


def extract_urls(text: str) -> list[str]:
    """Extract all deduplicated URLs from raw text or Markdown string.

    Preserves the order of appearance.
    """
    if not text:
        return []

    found_urls: list[str] = []

    # 1. Extract Markdown URLs first
    for match in MARKDOWN_LINK_PATTERN.finditer(text):
        url = clean_url(match.group(1))
        if url:
            found_urls.append(url)

    # 2. Extract raw URLs
    for match in RAW_URL_PATTERN.finditer(text):
        url = clean_url(match.group(0))
        if url:
            found_urls.append(url)

    # 3. Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for u in found_urls:
        if u not in seen:
            seen.add(u)
            deduped.append(u)

    return deduped


def is_image_url(url: str) -> bool:
    """Determine if a URL points to an image resource."""
    try:
        parsed = urlparse(url)
        path = parsed.path.lower()

        # Check path extension
        for ext in IMAGE_EXTENSIONS:
            if path.endswith(ext):
                return True

        # Check query parameters (e.g. ?format=jpg or ?fm=webp or ?ext=png)
        qs = parse_qs(parsed.query)
        for key in ("format", "fm", "ext", "mime"):
            if key in qs:
                val = qs[key][0].lower()
                if any(ext.lstrip(".") in val for ext in IMAGE_EXTENSIONS):
                    return True

        # Common image CDN path patterns
        if any(keyword in path for keyword in ("/images/", "/image/", "/img/", "/photos/")):
            # If it's not explicitly a video host
            if not is_video_url(url):
                return True

    except Exception:
        pass

    return False


def is_video_url(url: str) -> bool:
    """Determine if a URL points to a video resource or video platform."""
    try:
        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        path = parsed.path.lower()

        # Check hostname
        if netloc in VIDEO_HOSTS or any(netloc.endswith("." + host) for host in VIDEO_HOSTS):
            return True

        # Check path extension
        for ext in VIDEO_EXTENSIONS:
            if path.endswith(ext):
                return True

        # Common video path keywords
        if any(keyword in path for keyword in ("/watch", "/video/", "/videos/", "/reel/", "/shorts/")):
            return True

    except Exception:
        pass

    return False


def classify_urls(urls: list[str]) -> dict[str, list[str]]:
    """Classify a list of URLs into 'images', 'videos', and 'others'."""
    classified: dict[str, list[str]] = {
        "images": [],
        "videos": [],
        "others": [],
    }

    for url in urls:
        if is_video_url(url):
            classified["videos"].append(url)
        elif is_image_url(url):
            classified["images"].append(url)
        else:
            # Fallback check: if it looks like a web resource, classify as others
            classified["others"].append(url)

    return classified
