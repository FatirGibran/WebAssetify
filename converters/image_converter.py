"""Image download and WebP optimization module.

Uses aiohttp for non-blocking downloads and Pillow offloaded to asyncio.to_thread
for WebP compression under memory constraints.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import aiohttp
from PIL import Image, ImageOps

from config import config

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MB limit to prevent OOM


def _process_image_to_webp(
    image_data: bytes,
    output_path: Path,
    quality: int,
    max_dimension: int | None = None,
) -> bool:
    """Synchronous worker function to convert image bytes to .webp via Pillow.

    Includes EXIF orientation correction and dimension downscaling.
    Offloaded to asyncio.to_thread.
    """
    try:
        with Image.open(io.BytesIO(image_data)) as raw_img:
            # 1. Correct orientation using EXIF transpose
            img = ImageOps.exif_transpose(raw_img)
            if img is None:
                img = raw_img

            # 2. Downscale if dimension exceeds max_dimension
            if max_dimension and (img.width > max_dimension or img.height > max_dimension):
                ratio = min(max_dimension / img.width, max_dimension / img.height)
                new_width = max(1, int(img.width * ratio))
                new_height = max(1, int(img.height * ratio))
                resample = getattr(Image, "Resampling", Image).LANCZOS
                img = img.resize((new_width, new_height), resample=resample)

            # 3. Handle color mode conversions
            if img.mode in ("RGBA", "LA"):
                converted = img
            elif img.mode == "P":
                # Check for transparency in palette
                if "transparency" in img.info:
                    converted = img.convert("RGBA")
                else:
                    converted = img.convert("RGB")
            elif img.mode == "CMYK":
                converted = img.convert("RGB")
            elif img.mode not in ("RGB", "RGBA"):
                converted = img.convert("RGB")
            else:
                converted = img

            output_path.parent.mkdir(parents=True, exist_ok=True)
            converted.save(
                output_path,
                format="WEBP",
                quality=quality,
                optimize=True,
            )
        return True
    except Exception as e:
        logger.error("Failed to convert image to WebP at %s: %s", output_path, e)
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        return False


class ImageConverter:
    """Orchestrates asynchronous downloading and WebP optimization."""

    def __init__(
        self,
        quality: int | None = None,
        max_image_dimension: int | None = None,
        max_concurrent_downloads: int = 3,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self.quality = quality or config.webp_quality
        self.max_dimension = max_image_dimension or config.max_image_dimension
        self.semaphore = asyncio.Semaphore(max_concurrent_downloads)
        self._external_session = session
        self.stats: list[dict[str, Any]] = []

    @property
    def total_savings(self) -> dict[str, Any]:
        """Aggregate original vs converted size metrics across all processed images."""
        total_orig = sum(s.get("original_bytes", 0) for s in self.stats)
        total_conv = sum(s.get("converted_bytes", 0) for s in self.stats)
        saved = max(0, total_orig - total_conv)
        pct = (saved / total_orig * 100) if total_orig > 0 else 0.0
        return {
            "original_bytes": total_orig,
            "converted_bytes": total_conv,
            "saved_bytes": saved,
            "saved_percentage": pct,
        }

    @staticmethod
    def _generate_filename(url: str, index: int) -> str:
        """Derive a clean, unique file stem from URL or generate a fallback name."""
        parsed = urlparse(url)
        raw_name = Path(parsed.path).stem

        # Sanitize filename
        clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', raw_name).strip('_')
        if not clean_name or clean_name.lower() in ("image", "photo", "img", "download"):
            url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
            clean_name = f"image_{index:03d}_{url_hash}"
        else:
            clean_name = f"{index:03d}_{clean_name[:40]}"

        return f"{clean_name}.webp"

    async def convert_direct_image(
        self,
        image_bytes: bytes,
        output_path: Path,
        source_name: str = "direct_upload",
    ) -> Path | None:
        """Optimize direct image bytes (e.g. from Telegram photo/file) to .webp."""
        if len(image_bytes) > MAX_IMAGE_BYTES:
            logger.warning(
                "Direct image %s exceeds size limit (%d bytes)",
                source_name,
                len(image_bytes),
            )
            return None

        success = await asyncio.to_thread(
            _process_image_to_webp,
            image_bytes,
            output_path,
            self.quality,
            self.max_dimension,
        )

        if success and output_path.exists():
            out_size = output_path.stat().st_size
            self.stats.append({
                "source": source_name,
                "output_name": output_path.name,
                "original_bytes": len(image_bytes),
                "converted_bytes": out_size,
                "saved_bytes": max(0, len(image_bytes) - out_size),
            })
            logger.info("Successfully converted direct image %s -> %s", source_name, output_path.name)
            return output_path

        return None

    async def download_and_convert(
        self,
        url: str,
        output_dir: Path,
        index: int,
        session: aiohttp.ClientSession,
    ) -> Path | None:
        """Download an image from a URL and optimize it into a .webp file."""
        filename = self._generate_filename(url, index)
        output_path = output_dir / filename

        async with self.semaphore:
            try:
                timeout = aiohttp.ClientTimeout(total=25)
                async with session.get(
                    url,
                    headers=DEFAULT_HEADERS,
                    timeout=timeout,
                    allow_redirects=True,
                ) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Failed to download image %s: HTTP %d", url, resp.status
                        )
                        return None

                    # Check Content-Type if available
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if content_type and not (
                        "image" in content_type
                        or "octet-stream" in content_type
                        or "binary" in content_type
                    ):
                        logger.warning(
                            "Skipping non-image Content-Type '%s' for %s",
                            content_type,
                            url,
                        )
                        return None

                    content = await resp.read()
                    if len(content) > MAX_IMAGE_BYTES:
                        logger.warning(
                            "Image %s exceeds size limit (%d bytes)",
                            url,
                            len(content),
                        )
                        return None

                    if not content:
                        logger.warning("Empty content received for %s", url)
                        return None

                # Offload Pillow conversion to thread pool
                success = await asyncio.to_thread(
                    _process_image_to_webp,
                    content,
                    output_path,
                    self.quality,
                    self.max_dimension,
                )

                if success and output_path.exists():
                    out_size = output_path.stat().st_size
                    self.stats.append({
                        "source": url,
                        "output_name": output_path.name,
                        "original_bytes": len(content),
                        "converted_bytes": out_size,
                        "saved_bytes": max(0, len(content) - out_size),
                    })
                    logger.info("Successfully optimized %s -> %s", url, output_path.name)
                    return output_path

            except Exception as e:
                logger.error("Error processing image %s: %s", url, e)

        return None

    async def convert_all(
        self,
        urls: list[str],
        output_dir: Path,
    ) -> list[Path]:
        """Process a list of image URLs concurrently and save to output_dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        results: list[Path] = []

        if not urls:
            return results

        if self._external_session is not None:
            session = self._external_session
            tasks = [
                self.download_and_convert(url, output_dir, i + 1, session)
                for i, url in enumerate(urls)
            ]
            completed = await asyncio.gather(*tasks, return_exceptions=True)
        else:
            async with aiohttp.ClientSession() as session:
                tasks = [
                    self.download_and_convert(url, output_dir, i + 1, session)
                    for i, url in enumerate(urls)
                ]
                completed = await asyncio.gather(*tasks, return_exceptions=True)

        for res in completed:
            if isinstance(res, Path):
                results.append(res)
            elif isinstance(res, Exception):
                logger.error("Image conversion task failed with error: %s", res)

        return results
