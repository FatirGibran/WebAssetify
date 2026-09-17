"""Command Line Interface (CLI) for WebAssetify.

Allows headless execution of document parsing, media harvesting, WebP/WebM optimization,
zip bundling, and optional Google Drive delivery without requiring the Telegram bot.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from config import config
from converters.image_converter import ImageConverter
from converters.video_converter import VideoConverter
from parsers.docx_parser import extract_urls_from_docx
from parsers.html_parser import extract_urls_from_html
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.universal import (
    classify_urls,
    extract_urls,
    extract_urls_from_json,
    extract_urls_from_tabular,
)
from storage.gdrive import GoogleDriveStorage, _create_bundle_zip_sync

logger = logging.getLogger("webassetify-cli")


def parse_input_source(source: str) -> list[str]:
    """Extract candidate URLs from a file path or raw text string."""
    source_path = Path(source)
    if source_path.is_file():
        ext = source_path.suffix.lower()
        raw_bytes = source_path.read_bytes()
        if ext in (".txt", ".md"):
            return extract_urls(raw_bytes.decode("utf-8", errors="replace"))
        if ext in (".html", ".htm"):
            return extract_urls_from_html(raw_bytes)
        if ext in (".csv", ".tsv"):
            return extract_urls_from_tabular(raw_bytes.decode("utf-8", errors="replace"))
        if ext == ".json":
            return extract_urls_from_json(raw_bytes.decode("utf-8", errors="replace"))
        if ext == ".pdf":
            return extract_urls_from_pdf(raw_bytes)
        if ext == ".docx":
            return extract_urls_from_docx(raw_bytes)
        # Fallback to plain text scan
        return extract_urls(raw_bytes.decode("utf-8", errors="replace"))

    # If not a file, treat as direct text or URL
    return extract_urls(source)


async def run_pipeline(
    source: str,
    output_dir: Path,
    quality: int,
    max_dimension: int,
    max_video_height: int,
    create_zip: bool,
    upload_drive: bool,
) -> dict[str, Any]:
    """Execute the media harvesting and conversion pipeline asynchronously."""
    output_dir.mkdir(parents=True, exist_ok=True)
    images_dir = output_dir / "images"
    videos_dir = output_dir / "videos"

    urls = parse_input_source(source)
    if not urls:
        logger.warning("No URLs discovered in the provided input source.")
        return {"success": False, "message": "No URLs found"}

    classified = classify_urls(urls)
    image_urls = classified["images"]
    video_urls = classified["videos"]
    other_urls = classified["others"]

    if not image_urls and not video_urls and other_urls:
        image_urls = other_urls

    logger.info("Found %d URLs: %d images, %d videos", len(urls), len(image_urls), len(video_urls))

    image_converter = ImageConverter(
        quality=quality,
        max_image_dimension=max_dimension,
    )
    converted_images = await image_converter.convert_all(image_urls, images_dir)

    video_converter = VideoConverter(
        max_height=max_video_height,
        scratch_dir=output_dir,
    )
    converted_videos = await video_converter.convert_all(video_urls, videos_dir)

    savings = image_converter.total_savings

    # Generate local manifest
    manifest_data = {
        "service": "WebAssetify CLI",
        "source": source,
        "images_count": len(converted_images),
        "videos_count": len(converted_videos),
        "savings": savings,
    }
    manifest_file = output_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    zip_file: Path | None = None
    if create_zip:
        zip_file = output_dir / "assets_bundle.zip"
        await asyncio.to_thread(_create_bundle_zip_sync, output_dir, zip_file)

    drive_result: dict[str, Any] | None = None
    if upload_drive:
        try:
            gdrive = GoogleDriveStorage()
            drive_result = await gdrive.upload_pipeline(
                output_dir,
                user_id="cli_user",
                session_stats=savings,
            )
        except Exception as e:
            logger.error("Drive upload failed: %s", e)

    return {
        "success": True,
        "total_urls": len(urls),
        "images_count": len(converted_images),
        "videos_count": len(converted_videos),
        "savings": savings,
        "zip_created": zip_file.exists() if zip_file else False,
        "drive_result": drive_result,
        "output_dir": str(output_dir),
    }


def build_parser() -> argparse.ArgumentParser:
    """Build command line argument parser."""
    parser = argparse.ArgumentParser(
        prog="webassetify",
        description="⚡ WebAssetify: Automated Media Harvester and Web Optimizer (.webp / .webm)",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version="%(prog)s 1.1.0",
        help="Show program version and exit",
    )
    parser.add_argument(
        "source",
        help="Input document file path (.pdf, .docx, .html, .csv, .json, .md, .txt) or direct URL/text",
    )
    parser.add_argument(
        "-o", "--output",
        default="./output",
        help="Destination directory for optimized assets (default: ./output)",
    )
    parser.add_argument(
        "-q", "--quality",
        type=int,
        default=config.webp_quality,
        help=f"WebP image compression quality (default: {config.webp_quality})",
    )
    parser.add_argument(
        "-d", "--max-dimension",
        type=int,
        default=config.max_image_dimension,
        help=f"Max image dimension downscaling limit (default: {config.max_image_dimension})",
    )
    parser.add_argument(
        "-v", "--max-video-height",
        type=int,
        default=config.max_video_height,
        help=f"Max video height resolution (default: {config.max_video_height})",
    )
    parser.add_argument(
        "--zip",
        action="store_true",
        help="Create assets_bundle.zip in the output directory",
    )
    parser.add_argument(
        "--upload-drive",
        action="store_true",
        help="Upload the generated assets and bundle to Google Drive",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed debug logs",
    )
    return parser


def main() -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args()

    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s]: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    print("\n⚡ WebAssetify CLI: Initializing pipeline...")
    output_dir = Path(args.output).resolve()

    result = asyncio.run(
        run_pipeline(
            source=args.source,
            output_dir=output_dir,
            quality=args.quality,
            max_dimension=args.max_dimension,
            max_video_height=args.max_video_height,
            create_zip=args.zip,
            upload_drive=args.upload_drive,
        )
    )

    if not result.get("success"):
        print(f"❌ Error: {result.get('message', 'Failed to process assets')}")
        return 1

    savings = result["savings"]
    orig_mb = savings.get("original_bytes", 0) / (1024 * 1024)
    conv_mb = savings.get("converted_bytes", 0) / (1024 * 1024)
    pct = savings.get("saved_percentage", 0.0)

    print("\n" + "=" * 50)
    print("✅ WebAssetify Processing Complete!")
    print("=" * 50)
    print(f"📁 Output Directory : {output_dir}")
    print(f"🖼️  WebP Images      : {result['images_count']}")
    print(f"🎥 WebM Videos      : {result['videos_count']}")
    if orig_mb > 0:
        print(f"💾 Storage Saved    : {orig_mb:.2f} MB ➔ {conv_mb:.2f} MB ({pct:.1f}% reduction)")
    if result.get("zip_created"):
        print(f"📦 Bundle Archive   : {output_dir / 'assets_bundle.zip'}")
    if result.get("drive_result"):
        print(f"🔗 Google Drive URL : {result['drive_result']['web_view_link']}")
    print("=" * 50 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
