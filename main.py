"""WebAssetify entrypoint and orchestrator.

Runs a keep-alive aiohttp micro-webserver concurrently with python-telegram-bot v20+ polling loop
in the same asyncio event loop. Supports URL extraction from documents, direct media optimization,
Google Drive delivery with manifest reports, an interactive web dashboard, and Telegram inline keyboards.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import config
from converters.image_converter import ImageConverter
from converters.video_converter import VideoConverter, _transcode_to_webm_sync
from parsers.docx_parser import extract_urls_from_docx
from parsers.html_parser import extract_urls_from_html
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.universal import (
    classify_urls,
    extract_urls,
    extract_urls_from_json,
    extract_urls_from_tabular,
)
from storage.gdrive import GoogleDriveStorage

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("webassetify")

# Service boot timestamp for uptime tracking
START_TIME = time.time()

# Supported document and media extensions
DOCUMENT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".html", ".htm", ".csv", ".tsv", ".json"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif", ".svg", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".m4v", ".avi", ".flv", ".wmv", ".ts"}


async def health_endpoint(request: web.Request) -> web.Response:
    """Keep-alive health check endpoint for UptimeRobot and Render."""
    uptime_seconds = int(time.time() - START_TIME)
    return web.json_response({
        "status": "alive",
        "service": "WebAssetify",
        "uptime_seconds": uptime_seconds,
    })


async def index_endpoint(request: web.Request) -> web.Response:
    """Serve a modern web dashboard to browser visitors and JSON to monitors."""
    accept = request.headers.get("Accept", "")
    if "text/html" in accept:
        uptime_seconds = int(time.time() - START_TIME)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        safe_cfg = config.to_safe_dict()

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WebAssetify — Live Status Dashboard</title>
    <style>
        :root {{
            --bg: #0b0f19;
            --card-bg: rgba(22, 30, 49, 0.7);
            --border: rgba(255, 255, 255, 0.08);
            --accent: #38bdf8;
            --accent-glow: rgba(56, 189, 248, 0.3);
            --success: #10b981;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }}
        body {{
            background-color: var(--bg);
            color: var(--text-main);
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            padding: 24px;
            background-image: radial-gradient(circle at top, #1e293b 0%, #0b0f19 100%);
        }}
        .container {{
            max-width: 640px;
            width: 100%;
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 40px;
            box-shadow: 0 20px 50px rgba(0,0,0,0.5);
        }}
        .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
        .title {{ font-size: 26px; font-weight: 700; letter-spacing: -0.5px; display: flex; align-items: center; gap: 10px; }}
        .badge {{
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(16, 185, 129, 0.12);
            color: var(--success);
            padding: 6px 14px;
            border-radius: 9999px;
            font-size: 13px;
            font-weight: 600;
            border: 1px solid rgba(16, 185, 129, 0.25);
        }}
        .pulse {{
            width: 8px; height: 8px; background: var(--success); border-radius: 50%;
            box-shadow: 0 0 10px var(--success);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{
            0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
            70% {{ transform: scale(1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }}
            100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
        }}
        .subtitle {{ color: var(--text-muted); margin-bottom: 28px; font-size: 14px; line-height: 1.6; }}
        .grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 32px; }}
        .card {{
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
        }}
        .card-label {{ font-size: 13px; color: var(--text-muted); margin-bottom: 6px; }}
        .card-val {{ font-size: 20px; font-weight: 700; color: var(--text-main); }}
        .actions {{ display: flex; gap: 12px; }}
        .btn {{
            flex: 1;
            padding: 14px 20px;
            border-radius: 12px;
            font-size: 14px;
            font-weight: 600;
            text-align: center;
            text-decoration: none;
            transition: all 0.2s ease;
            cursor: pointer;
        }}
        .btn-primary {{
            background: var(--accent);
            color: #0b0f19;
            box-shadow: 0 4px 14px var(--accent-glow);
        }}
        .btn-primary:hover {{ background: #7dd3fc; }}
        .btn-secondary {{
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-main);
            border: 1px solid var(--border);
        }}
        .btn-secondary:hover {{ background: rgba(255, 255, 255, 0.1); }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">⚡ WebAssetify</div>
            <div class="badge"><div class="pulse"></div> Live & Operational</div>
        </div>
        <p class="subtitle">
            High-performance asynchronous asset harvesting and web optimization pipeline (.webp/.webm) with automated Google Drive delivery.
        </p>
        <div class="grid">
            <div class="card">
                <div class="card-label">Uptime</div>
                <div class="card-val">{hours}h {minutes}m {seconds}s</div>
            </div>
            <div class="card">
                <div class="card-label">Server Port</div>
                <div class="card-val">{config.port}</div>
            </div>
            <div class="card">
                <div class="card-label">WebP Quality</div>
                <div class="card-val">{config.webp_quality}</div>
            </div>
            <div class="card">
                <div class="card-label">Max Dimension</div>
                <div class="card-val">{config.max_image_dimension}px</div>
            </div>
        </div>
        <div class="actions">
            <a href="https://github.com/Fatirrr08/WebAssetify" target="_blank" class="btn btn-secondary">🐙 GitHub Repo</a>
            <a href="/health" class="btn btn-primary">🔍 JSON Health API</a>
        </div>
    </div>
</body>
</html>"""
        return web.Response(text=html, content_type="text/html")
    return await health_endpoint(request)


def create_web_app() -> web.Application:
    """Create the aiohttp micro-server application."""
    app = web.Application()
    app.router.add_get("/", index_endpoint)
    app.router.add_get("/health", health_endpoint)
    return app


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    welcome_text = (
        "⚡ *Welcome to WebAssetify!*\n\n"
        "I am your automated asset harvesting and web optimization pipeline.\n\n"
        "*What I do:*\n"
        "• Extract media links from documents (`.md`, `.txt`, `.pdf`, `.docx`, `.html`, `.csv`, `.json`) or raw text.\n"
        "• Accept direct photos and videos sent in chat for automatic web conversion.\n"
        "• Optimize images to lightweight *.webp* with EXIF correction.\n"
        "• Transcode videos to low-memory *.webm* via FFmpeg.\n"
        "• Upload everything to Google Drive with an `assets_bundle.zip` and manifest report.\n\n"
        "*How to use:*\n"
        "• Send me a document or raw URLs.\n"
        "• Send a photo or video directly.\n"
        "• Type /status to view system status and settings."
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📖 Help Guide", callback_data="cmd_help"),
            InlineKeyboardButton("📊 System Status", callback_data="cmd_status"),
        ],
        [
            InlineKeyboardButton("🐙 GitHub Repository", url="https://github.com/Fatirrr08/WebAssetify"),
        ],
    ])
    if update.message:
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "📖 *WebAssetify Help*\n\n"
        "*Supported Documents:*\n"
        "• `.md` / `.txt` - Plain text and Markdown links (`[title](url)` or `![alt](url)`)\n"
        "• `.pdf` - Visible text and embedded URI hyperlink annotations\n"
        "• `.docx` - Word text, tables, and internal XML hyperlinks\n"
        "• `.html` / `.htm` - HTML tags (`img`, `video`, `source`, `a`, inline CSS)\n"
        "• `.csv` / `.tsv` - Tabular spreadsheets with URL columns\n"
        "• `.json` - JSON files containing media links\n\n"
        "*Direct Media:*\n"
        "• Send any Photo or Video directly in chat.\n\n"
        "*Commands:*\n"
        "• `/start` - Introduction and usage overview\n"
        "• `/help` - Show this help menu\n"
        "• `/status` - Uptime, settings, and memory diagnostics\n"
        "• `/ping` - Latency check\n\n"
        "*Outputs:*\n"
        "A public Google Drive folder containing `images/`, `videos/`, `manifest.json`, and `assets_bundle.zip`."
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📊 System Status", callback_data="cmd_status"),
            InlineKeyboardButton("🐙 GitHub", url="https://github.com/Fatirrr08/WebAssetify"),
        ]
    ])
    if update.message:
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command: reports service health, uptime, and configuration."""
    uptime_seconds = int(time.time() - START_TIME)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    safe_cfg = config.to_safe_dict()

    status_text = (
        "📊 *WebAssetify System Status*\n\n"
        f"• *Status:* 🟢 Operational\n"
        f"• *Uptime:* `{uptime_str}`\n"
        f"• *Server Port:* `{config.port}`\n"
        f"• *WebP Quality:* `{config.webp_quality}`\n"
        f"• *Max Image Dimension:* `{config.max_image_dimension}px`\n"
        f"• *Max Video Height:* `{config.max_video_height}p`\n"
        f"• *Supported Docs:* `{len(DOCUMENT_EXTENSIONS)} formats`\n"
        f"• *Drive Parent Folder:* `{safe_cfg['gdrive_parent_folder_id']}`\n"
        f"• *Drive Credentials:* `{safe_cfg['gdrive_service_account_json']}`"
    )
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🔄 Refresh Status", callback_data="cmd_status"),
            InlineKeyboardButton("📖 Help Guide", callback_data="cmd_help"),
        ],
        [
            InlineKeyboardButton("🐙 GitHub Repository", url="https://github.com/Fatirrr08/WebAssetify"),
        ],
    ])
    if update.message:
        await update.message.reply_text(
            status_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard,
        )


async def ping_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /ping command: fast latency diagnostic."""
    start = time.time()
    if update.message:
        msg = await update.message.reply_text("🏓 Pong...")
        elapsed_ms = int((time.time() - start) * 1000)
        await msg.edit_text(f"🏓 *Pong!* `({elapsed_ms} ms)`", parse_mode=ParseMode.MARKDOWN)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle interactive inline keyboard button callbacks."""
    query = update.callback_query
    if not query:
        return
    await query.answer()

    if query.data == "cmd_help":
        help_text = (
            "📖 *WebAssetify Help*\n\n"
            "*Supported Documents:*\n"
            "• `.md` / `.txt` - Plain text and Markdown links\n"
            "• `.pdf` - Visible text & URI hyperlink annotations\n"
            "• `.docx` - Word text, tables, & internal XML hyperlinks\n"
            "• `.html` / `.htm` - HTML tags (`img`, `video`, `source`, `a`, inline CSS)\n"
            "• `.csv` / `.tsv` - Tabular spreadsheets with URL columns\n"
            "• `.json` - JSON files containing media links\n\n"
            "*Direct Media:*\n"
            "• Send any Photo or Video directly in chat.\n\n"
            "*Outputs:*\n"
            "A public Google Drive folder containing `images/`, `videos/`, `manifest.json`, and `assets_bundle.zip`."
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📊 System Status", callback_data="cmd_status"),
                InlineKeyboardButton("🐙 GitHub", url="https://github.com/Fatirrr08/WebAssetify"),
            ]
        ])
        try:
            await query.edit_message_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        except Exception:
            pass

    elif query.data == "cmd_status":
        uptime_seconds = int(time.time() - START_TIME)
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        safe_cfg = config.to_safe_dict()

        status_text = (
            "📊 *WebAssetify System Status*\n\n"
            f"• *Status:* 🟢 Operational\n"
            f"• *Uptime:* `{uptime_str}`\n"
            f"• *Server Port:* `{config.port}`\n"
            f"• *WebP Quality:* `{config.webp_quality}`\n"
            f"• *Max Image Dimension:* `{config.max_image_dimension}px`\n"
            f"• *Max Video Height:* `{config.max_video_height}p`\n"
            f"• *Supported Docs:* `{len(DOCUMENT_EXTENSIONS)} formats`\n"
            f"• *Drive Parent Folder:* `{safe_cfg['gdrive_parent_folder_id']}`\n"
            f"• *Drive Credentials:* `{safe_cfg['gdrive_service_account_json']}`"
        )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Refresh Status", callback_data="cmd_status"),
                InlineKeyboardButton("📖 Help Guide", callback_data="cmd_help"),
            ],
            [
                InlineKeyboardButton("🐙 GitHub Repository", url="https://github.com/Fatirrr08/WebAssetify"),
            ],
        ])
        try:
            await query.edit_message_text(status_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        except Exception:
            pass


async def _process_pipeline(
    raw_text: str | None,
    doc_bytes: bytes | None,
    doc_filename: str | None,
    user_id: int | str,
    status_msg: Any,
) -> None:
    """Execute parsing, optimization, and Google Drive upload with guaranteed cleanup."""
    # Create unique scratch directory for this job
    job_id = uuid.uuid4().hex[:10]
    scratch_dir = Path(config.temp_dir) / f"job_{job_id}"
    images_dir = scratch_dir / "images"
    videos_dir = scratch_dir / "videos"

    scratch_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)
    videos_dir.mkdir(exist_ok=True)

    try:
        # Step 1: Parse URLs from input
        await status_msg.edit_text("🔍 *Step 1/4:* Parsing documents and extracting URLs...", parse_mode=ParseMode.MARKDOWN)

        extracted_urls: list[str] = []

        if raw_text:
            extracted_urls = extract_urls(raw_text)
        elif doc_bytes and doc_filename:
            ext = Path(doc_filename).suffix.lower()
            if ext in (".txt", ".md"):
                text_content = doc_bytes.decode("utf-8", errors="replace")
                extracted_urls = extract_urls(text_content)
            elif ext in (".html", ".htm"):
                extracted_urls = extract_urls_from_html(doc_bytes)
            elif ext in (".csv", ".tsv"):
                text_content = doc_bytes.decode("utf-8", errors="replace")
                extracted_urls = extract_urls_from_tabular(text_content)
            elif ext == ".json":
                text_content = doc_bytes.decode("utf-8", errors="replace")
                extracted_urls = extract_urls_from_json(text_content)
            elif ext == ".pdf":
                extracted_urls = extract_urls_from_pdf(doc_bytes)
            elif ext == ".docx":
                extracted_urls = extract_urls_from_docx(doc_bytes)
            else:
                await status_msg.edit_text(
                    f"⚠️ Unsupported document format `{ext}`. "
                    f"Please send `{', '.join(sorted(DOCUMENT_EXTENSIONS))}`.",
                    parse_mode=ParseMode.MARKDOWN,
                )
                return

        if not extracted_urls:
            await status_msg.edit_text(
                "⚠️ *No URLs found in the provided input.*\n"
                "Please make sure your message or document contains valid web links.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        classified = classify_urls(extracted_urls)
        image_urls = classified["images"]
        video_urls = classified["videos"]
        other_urls = classified["others"]

        # If only other URLs were found, treat them as candidate images to inspect
        if not image_urls and not video_urls and other_urls:
            image_urls = other_urls

        total_assets = len(image_urls) + len(video_urls)
        if total_assets == 0:
            await status_msg.edit_text(
                "⚠️ *No media URLs detected.*\n"
                f"Found {len(extracted_urls)} generic URLs, but none were recognized as media.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        await status_msg.edit_text(
            f"🔍 *Found {len(extracted_urls)} URLs*\n"
            f"• Images to optimize: {len(image_urls)}\n"
            f"• Videos to transcode: {len(video_urls)}\n\n"
            f"⚙️ *Step 2/4:* Optimizing media assets...",
            parse_mode=ParseMode.MARKDOWN,
        )

        # Step 2: Convert images to .webp
        image_converter = ImageConverter()
        converted_images = await image_converter.convert_all(image_urls, images_dir)

        # Step 3: Transcode videos to .webm
        if video_urls:
            await status_msg.edit_text(
                f"⚙️ *Step 2/4:* Images converted ({len(converted_images)}).\n"
                f"Now transcoding {len(video_urls)} video(s) to WebM (this may take a moment)...",
                parse_mode=ParseMode.MARKDOWN,
            )

        video_converter = VideoConverter()
        converted_videos = await video_converter.convert_all(video_urls, videos_dir)

        if not converted_images and not converted_videos:
            await status_msg.edit_text(
                "❌ *Media conversion failed.*\n"
                "None of the media links could be downloaded or transcoded. "
                "Please verify the links are publicly accessible.",
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        # Step 4: Upload to Google Drive
        await status_msg.edit_text(
            f"☁️ *Step 3/4:* Packaging and uploading to Google Drive...\n"
            f"• WebP Images: {len(converted_images)}\n"
            f"• WebM Videos: {len(converted_videos)}",
            parse_mode=ParseMode.MARKDOWN,
        )

        savings = image_converter.total_savings
        gdrive = GoogleDriveStorage()
        upload_result = await gdrive.upload_pipeline(
            scratch_dir,
            user_id=user_id,
            session_stats=savings,
        )

        # Step 5: Send final report
        folder_link = upload_result["web_view_link"]
        folder_name = upload_result["folder_name"]

        savings_text = ""
        if savings.get("original_bytes", 0) > 0:
            orig_mb = savings["original_bytes"] / (1024 * 1024)
            conv_mb = savings["converted_bytes"] / (1024 * 1024)
            pct = savings.get("saved_percentage", 0.0)
            savings_text = f"💾 *Storage Saved:* {orig_mb:.2f} MB ➔ {conv_mb:.2f} MB ({pct:.1f}% reduction)\n"

        final_message = (
            "✅ *Asset Optimization & Upload Complete!*\n\n"
            f"📁 *Folder:* `{folder_name}`\n"
            f"🖼️ *Optimized Images (.webp):* {upload_result['images_count']}\n"
            f"🎥 *Transcoded Videos (.webm):* {upload_result['videos_count']}\n"
            f"{savings_text}"
            f"📦 *Bundle Zip:* Included (`assets_bundle.zip`)\n"
            f"📄 *Manifest:* Included (`manifest.json`)\n\n"
            f"🔗 [Open Google Drive Folder]({folder_link})"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Open Google Drive Folder", url=folder_link)],
            [InlineKeyboardButton("📊 View System Status", callback_data="cmd_status")],
        ])
        await status_msg.edit_text(
            final_message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
            reply_markup=keyboard,
        )

    except Exception as e:
        logger.exception("Error occurred in asset processing pipeline: %s", e)
        try:
            await status_msg.edit_text(
                f"❌ *An error occurred during processing:*\n`{str(e)}`",
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception:
            pass

    finally:
        # Cleanup Guarantee: always delete scratch directory to prevent container disk exhaustion
        try:
            if scratch_dir.exists():
                shutil.rmtree(scratch_dir, ignore_errors=True)
                logger.info("Cleaned up scratch directory: %s", scratch_dir)
        except Exception as e:
            logger.warning("Failed to clean up scratch directory %s: %s", scratch_dir, e)


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming text messages containing links."""
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    status_msg = await update.message.reply_text(
        "⏳ *WebAssetify:* Received request. Initializing pipeline...",
        parse_mode=ParseMode.MARKDOWN,
    )

    await _process_pipeline(
        raw_text=update.message.text,
        doc_bytes=None,
        doc_filename=None,
        user_id=user_id,
        status_msg=status_msg,
    )


async def handle_photo_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle direct Telegram photo uploads."""
    if not update.message or not update.message.photo:
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    status_msg = await update.message.reply_text(
        "⏳ *WebAssetify:* Downloading photo...",
        parse_mode=ParseMode.MARKDOWN,
    )

    photo = update.message.photo[-1]  # Highest resolution
    job_id = uuid.uuid4().hex[:10]
    scratch_dir = Path(config.temp_dir) / f"job_{job_id}"
    images_dir = scratch_dir / "images"

    scratch_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(exist_ok=True)

    try:
        tg_file = await photo.get_file()
        photo_bytes = bytes(await tg_file.download_as_bytearray())

        await status_msg.edit_text(
            "⚙️ *WebAssetify:* Optimizing photo to WebP format...",
            parse_mode=ParseMode.MARKDOWN,
        )

        image_converter = ImageConverter()
        out_filename = f"001_photo_{photo.file_unique_id}.webp"
        out_path = images_dir / out_filename

        res = await image_converter.convert_direct_image(
            photo_bytes,
            out_path,
            source_name=f"telegram_photo_{photo.file_unique_id}",
        )

        if not res:
            await status_msg.edit_text("❌ *Failed to optimize photo to WebP.*", parse_mode=ParseMode.MARKDOWN)
            return

        await status_msg.edit_text(
            "☁️ *WebAssetify:* Uploading optimized photo to Google Drive...",
            parse_mode=ParseMode.MARKDOWN,
        )

        savings = image_converter.total_savings
        gdrive = GoogleDriveStorage()
        upload_result = await gdrive.upload_pipeline(
            scratch_dir,
            user_id=user_id,
            session_stats=savings,
        )

        folder_link = upload_result["web_view_link"]
        folder_name = upload_result["folder_name"]

        savings_text = ""
        if savings.get("original_bytes", 0) > 0:
            orig_kb = savings["original_bytes"] / 1024
            conv_kb = savings["converted_bytes"] / 1024
            pct = savings.get("saved_percentage", 0.0)
            savings_text = f"💾 *Storage Saved:* {orig_kb:.1f} KB ➔ {conv_kb:.1f} KB ({pct:.1f}% reduction)\n"

        final_message = (
            "✅ *Photo Optimization & Upload Complete!*\n\n"
            f"📁 *Folder:* `{folder_name}`\n"
            f"🖼️ *Optimized Image:* `{out_filename}`\n"
            f"{savings_text}"
            f"📦 *Bundle Zip:* Included (`assets_bundle.zip`)\n"
            f"📄 *Manifest:* Included (`manifest.json`)\n\n"
            f"🔗 [Open Google Drive Folder]({folder_link})"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Open Google Drive Folder", url=folder_link)],
        ])
        await status_msg.edit_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception as e:
        logger.exception("Failed to process direct photo: %s", e)
        try:
            await status_msg.edit_text(f"❌ *Error processing photo:*\n`{str(e)}`", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


async def handle_video_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle direct Telegram video uploads."""
    if not update.message or not update.message.video:
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    video = update.message.video
    filename = video.file_name or f"video_{video.file_unique_id}.mp4"

    status_msg = await update.message.reply_text(
        f"⏳ *WebAssetify:* Downloading video `{filename}`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    job_id = uuid.uuid4().hex[:10]
    scratch_dir = Path(config.temp_dir) / f"job_{job_id}"
    videos_dir = scratch_dir / "videos"

    scratch_dir.mkdir(parents=True, exist_ok=True)
    videos_dir.mkdir(exist_ok=True)

    try:
        tg_file = await video.get_file()
        video_bytes = bytes(await tg_file.download_as_bytearray())

        raw_video_path = scratch_dir / f"raw_{video.file_unique_id}.mp4"
        raw_video_path.write_bytes(video_bytes)

        await status_msg.edit_text(
            "⚙️ *WebAssetify:* Transcoding video to low-memory WebM (this may take a moment)...",
            parse_mode=ParseMode.MARKDOWN,
        )

        out_filename = f"001_{Path(filename).stem[:35]}.webm"
        out_path = videos_dir / out_filename

        success = await asyncio.to_thread(_transcode_to_webm_sync, raw_video_path, out_path)
        raw_video_path.unlink(missing_ok=True)

        if not success or not out_path.exists():
            await status_msg.edit_text("❌ *Failed to transcode video to WebM.*", parse_mode=ParseMode.MARKDOWN)
            return

        await status_msg.edit_text(
            "☁️ *WebAssetify:* Uploading transcoded video to Google Drive...",
            parse_mode=ParseMode.MARKDOWN,
        )

        orig_size = len(video_bytes)
        conv_size = out_path.stat().st_size
        saved = max(0, orig_size - conv_size)
        pct = (saved / orig_size * 100) if orig_size > 0 else 0.0

        video_stats = {
            "original_bytes": orig_size,
            "converted_bytes": conv_size,
            "saved_bytes": saved,
            "saved_percentage": pct,
        }

        gdrive = GoogleDriveStorage()
        upload_result = await gdrive.upload_pipeline(
            scratch_dir,
            user_id=user_id,
            session_stats=video_stats,
        )

        folder_link = upload_result["web_view_link"]
        folder_name = upload_result["folder_name"]

        orig_mb = orig_size / (1024 * 1024)
        conv_mb = conv_size / (1024 * 1024)
        savings_text = f"💾 *Storage Saved:* {orig_mb:.2f} MB ➔ {conv_mb:.2f} MB ({pct:.1f}% reduction)\n"

        final_message = (
            "✅ *Video Transcoding & Upload Complete!*\n\n"
            f"📁 *Folder:* `{folder_name}`\n"
            f"🎥 *Transcoded Video:* `{out_filename}`\n"
            f"{savings_text}"
            f"📦 *Bundle Zip:* Included (`assets_bundle.zip`)\n"
            f"📄 *Manifest:* Included (`manifest.json`)\n\n"
            f"🔗 [Open Google Drive Folder]({folder_link})"
        )
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📂 Open Google Drive Folder", url=folder_link)],
        ])
        await status_msg.edit_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

    except Exception as e:
        logger.exception("Failed to process direct video: %s", e)
        try:
            await status_msg.edit_text(f"❌ *Error processing video:*\n`{str(e)}`", parse_mode=ParseMode.MARKDOWN)
        except Exception:
            pass
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming document uploads (documents or direct image files)."""
    if not update.message or not update.message.document:
        return

    document = update.message.document
    filename = document.file_name or "document"
    ext = Path(filename).suffix.lower()

    # Check if uploaded as a direct uncompressed image
    if ext in IMAGE_EXTENSIONS:
        user_id = update.effective_user.id if update.effective_user else "unknown"
        status_msg = await update.message.reply_text(
            f"⏳ *WebAssetify:* Downloading image `{filename}`...",
            parse_mode=ParseMode.MARKDOWN,
        )
        job_id = uuid.uuid4().hex[:10]
        scratch_dir = Path(config.temp_dir) / f"job_{job_id}"
        images_dir = scratch_dir / "images"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        images_dir.mkdir(exist_ok=True)

        try:
            tg_file = await document.get_file()
            img_bytes = bytes(await tg_file.download_as_bytearray())

            await status_msg.edit_text("⚙️ *WebAssetify:* Converting image to WebP...", parse_mode=ParseMode.MARKDOWN)
            image_converter = ImageConverter()
            out_filename = f"001_{Path(filename).stem[:35]}.webp"
            out_path = images_dir / out_filename

            res = await image_converter.convert_direct_image(img_bytes, out_path, source_name=filename)
            if not res:
                await status_msg.edit_text("❌ *Failed to convert image.*", parse_mode=ParseMode.MARKDOWN)
                return

            await status_msg.edit_text("☁️ *WebAssetify:* Uploading to Google Drive...", parse_mode=ParseMode.MARKDOWN)
            gdrive = GoogleDriveStorage()
            upload_result = await gdrive.upload_pipeline(scratch_dir, user_id=user_id, session_stats=image_converter.total_savings)

            folder_link = upload_result["web_view_link"]
            savings = image_converter.total_savings
            savings_text = ""
            if savings.get("original_bytes", 0) > 0:
                orig_kb = savings["original_bytes"] / 1024
                conv_kb = savings["converted_bytes"] / 1024
                pct = savings.get("saved_percentage", 0.0)
                savings_text = f"💾 *Storage Saved:* {orig_kb:.1f} KB ➔ {conv_kb:.1f} KB ({pct:.1f}% reduction)\n"

            final_message = (
                "✅ *Image Optimization & Upload Complete!*\n\n"
                f"📁 *Folder:* `{upload_result['folder_name']}`\n"
                f"🖼️ *Optimized Image:* `{out_filename}`\n"
                f"{savings_text}"
                f"🔗 [Open Google Drive Folder]({folder_link})"
            )
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📂 Open Google Drive Folder", url=folder_link)],
            ])
            await status_msg.edit_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)
        except Exception as e:
            logger.exception("Failed to process document image: %s", e)
            await status_msg.edit_text(f"❌ *Error:*\n`{str(e)}`", parse_mode=ParseMode.MARKDOWN)
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)
        return

    if ext not in DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(DOCUMENT_EXTENSIONS))
        await update.message.reply_text(
            f"⚠️ Unsupported file type `{ext}`.\n"
            f"Please upload one of the following: `{supported}`, or an image file.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user_id = update.effective_user.id if update.effective_user else "unknown"
    status_msg = await update.message.reply_text(
        f"⏳ *WebAssetify:* Downloading `{filename}`...",
        parse_mode=ParseMode.MARKDOWN,
    )

    try:
        tg_file = await document.get_file()
        doc_bytes = await tg_file.download_as_bytearray()

        await _process_pipeline(
            raw_text=None,
            doc_bytes=bytes(doc_bytes),
            doc_filename=filename,
            user_id=user_id,
            status_msg=status_msg,
        )
    except Exception as e:
        logger.exception("Failed to download Telegram document: %s", e)
        await status_msg.edit_text(
            f"❌ *Failed to download file from Telegram:*\n`{str(e)}`",
            parse_mode=ParseMode.MARKDOWN,
        )


async def run_server() -> None:
    """Run keep-alive aiohttp server and python-telegram-bot concurrently."""
    logger.info("Starting WebAssetify service...")
    logger.info("Configuration: %s", config.to_safe_dict())

    # 1. Setup aiohttp micro-webserver
    app = create_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=config.port)
    await site.start()
    logger.info("Micro HTTP keep-alive server listening on port %d", config.port)

    # 2. Check Telegram Bot Token
    if not config.telegram_bot_token:
        logger.warning(
            "TELEGRAM_BOT_TOKEN is not configured. Telegram bot polling will NOT start. "
            "Keep-alive HTTP server remains running on port %d.",
            config.port,
        )
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except NotImplementedError:
                pass
        await stop_event.wait()
        await runner.cleanup()
        return

    # 3. Setup Telegram Bot Application
    telegram_app = Application.builder().token(config.telegram_bot_token).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CommandHandler("help", help_command))
    telegram_app.add_handler(CommandHandler("status", status_command))
    telegram_app.add_handler(CommandHandler("ping", ping_command))
    telegram_app.add_handler(CallbackQueryHandler(handle_callback_query))

    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )
    telegram_app.add_handler(
        MessageHandler(filters.PHOTO, handle_photo_message)
    )
    telegram_app.add_handler(
        MessageHandler(filters.VIDEO, handle_video_message)
    )
    telegram_app.add_handler(
        MessageHandler(filters.Document.ALL, handle_document_message)
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    try:
        async with telegram_app:
            await telegram_app.initialize()
            await telegram_app.start()
            if telegram_app.updater:
                await telegram_app.updater.start_polling(drop_pending_updates=True)
                logger.info("Telegram Bot polling started successfully.")

            # Wait for shutdown signal
            await stop_event.wait()

            logger.info("Shutdown signal received. Stopping services...")
            if telegram_app.updater and telegram_app.updater.running:
                await telegram_app.updater.stop()
            await telegram_app.stop()
            await telegram_app.shutdown()

    finally:
        await runner.cleanup()
        logger.info("Micro HTTP server stopped. WebAssetify exited cleanly.")


def main() -> None:
    """Application main entrypoint."""
    try:
        asyncio.run(run_server())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Application exited by user signal.")


if __name__ == "__main__":
    main()
