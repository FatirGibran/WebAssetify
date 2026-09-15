"""WebAssetify entrypoint and orchestrator.

Runs a keep-alive aiohttp micro-webserver concurrently with python-telegram-bot v20+ polling loop
in the same asyncio event loop.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import uuid
from pathlib import Path
from typing import Any

from aiohttp import web
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from config import config
from converters.image_converter import ImageConverter
from converters.video_converter import VideoConverter
from parsers.docx_parser import extract_urls_from_docx
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.universal import classify_urls, extract_urls
from storage.gdrive import GoogleDriveStorage

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("webassetify")

# Supported document extensions
DOCUMENT_EXTENSIONS = {".txt", ".md", ".pdf", ".docx"}


async def health_endpoint(request: web.Request) -> web.Response:
    """Keep-alive health check endpoint for UptimeRobot and Render."""
    return web.json_response({"status": "alive", "service": "WebAssetify"})


def create_web_app() -> web.Application:
    """Create the aiohttp micro-server application."""
    app = web.Application()
    app.router.add_get("/", health_endpoint)
    app.router.add_get("/health", health_endpoint)
    return app


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    welcome_text = (
        "⚡ *Welcome to WebAssetify!*\n\n"
        "I am your automated asset harvesting and web optimization pipeline.\n\n"
        "*What I do:*\n"
        "• Extract media links from documents (`.md`, `.txt`, `.pdf`, `.docx`) or raw text.\n"
        "• Automatically convert images to modern, lightweight *.webp*.\n"
        "• Transcode video links (YouTube, MP4, etc.) to low-memory *.webm*.\n"
        "• Package everything into Google Drive with an `assets_bundle.zip`.\n\n"
        "*How to use:*\n"
        "Send me any supported document or paste a text message containing URLs."
    )
    if update.message:
        await update.message.reply_text(welcome_text, parse_mode=ParseMode.MARKDOWN)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "📖 *WebAssetify Help*\n\n"
        "*Supported Documents:*\n"
        "• `.md` / `.txt` - Plain text and Markdown links (`[title](url)` or `![alt](url)`)\n"
        "• `.pdf` - Visible text and embedded URI hyperlink annotations\n"
        "• `.docx` - Word text, tables, and internal XML hyperlinks\n\n"
        "*Direct Text:*\n"
        "You can also paste a list of URLs directly into chat.\n\n"
        "*Outputs:*\n"
        "A public Google Drive folder containing `images/`, `videos/`, and `assets_bundle.zip`."
    )
    if update.message:
        await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


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

        gdrive = GoogleDriveStorage()
        upload_result = await gdrive.upload_pipeline(scratch_dir, user_id=user_id)

        # Step 5: Send final report
        folder_link = upload_result["web_view_link"]
        folder_name = upload_result["folder_name"]
        final_message = (
            "✅ *Asset Optimization & Upload Complete!*\n\n"
            f"📁 *Folder:* `{folder_name}`\n"
            f"🖼️ *Optimized Images (.webp):* {upload_result['images_count']}\n"
            f"🎥 *Transcoded Videos (.webm):* {upload_result['videos_count']}\n"
            f"📦 *Bundle Zip:* Included (`assets_bundle.zip`)\n\n"
            f"🔗 [Open Google Drive Folder]({folder_link})"
        )
        await status_msg.edit_text(
            final_message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
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


async def handle_document_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle incoming document uploads (.md, .txt, .pdf, .docx)."""
    if not update.message or not update.message.document:
        return

    document = update.message.document
    filename = document.file_name or "document"
    ext = Path(filename).suffix.lower()

    if ext not in DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(DOCUMENT_EXTENSIONS))
        await update.message.reply_text(
            f"⚠️ Unsupported file type `{ext}`.\n"
            f"Please upload one of the following: `{supported}`.",
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
        # Keep alive HTTP server only
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
    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
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
