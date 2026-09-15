"""Video downloading and WebM transcoding module.

Uses yt-dlp for extraction and FFmpeg for low-memory VP9/Opus transcoding,
offloaded to worker threads via asyncio.to_thread to maintain async event loop responsiveness.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import yt_dlp

from config import config

logger = logging.getLogger(__name__)

# Single video transcoding lock to prevent OOM in 512 MB RAM container
_TRANSCODE_LOCK = asyncio.Lock()


def _download_video_sync(
    url: str,
    scratch_dir: Path,
    index: int,
    max_height: int,
) -> Path | None:
    """Download video stream synchronously using yt-dlp.

    Offloaded via asyncio.to_thread.
    """
    output_template = str(scratch_dir / f"raw_vid_{index:03d}_%(id)s.%(ext)s")

    ydl_opts: dict[str, Any] = {
        "format": f"bestvideo[height<={max_height}]+bestaudio/best[height<={max_height}]/best",
        "outtmpl": output_template,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # Cap download size at 100 MB to prevent disk / memory exhaustion
        "max_filesize": 100 * 1024 * 1024,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not info:
                return None

            # Find the downloaded file
            prepared_filename = ydl.prepare_filename(info)
            downloaded_path = Path(prepared_filename)

            # In some cases yt-dlp merges into .mkv or other extension
            if downloaded_path.exists():
                return downloaded_path

            # Search in scratch_dir for the file matching pattern
            candidates = list(scratch_dir.glob(f"raw_vid_{index:03d}_*"))
            if candidates:
                return candidates[0]

    except Exception as e:
        logger.error("yt-dlp download failed for %s: %s", url, e)

    return None


def _transcode_to_webm_sync(
    input_path: Path,
    output_path: Path,
    timeout_seconds: int = 300,
) -> bool:
    """Transcode a video file to WebM format using low-memory FFmpeg parameters.

    Offloaded via asyncio.to_thread.
    CLI Flags: -c:v libvpx-vp9 -crf 32 -b:v 0 -threads 1 -speed 4 -c:a libopus
    """
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(input_path),
        "-c:v",
        "libvpx-vp9",
        "-crf",
        "32",
        "-b:v",
        "0",
        "-threads",
        "1",
        "-speed",
        "4",
        "-c:a",
        "libopus",
        str(output_path),
    ]

    logger.info("Starting FFmpeg transcoding: %s -> %s", input_path.name, output_path.name)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )

        if proc.returncode != 0:
            logger.error("FFmpeg error (code %d): %s", proc.returncode, proc.stderr[-500:])
            return False

        if output_path.exists() and output_path.stat().st_size > 0:
            return True

    except subprocess.TimeoutExpired:
        logger.error("FFmpeg transcoding timed out after %d seconds", timeout_seconds)
    except Exception as e:
        logger.error("FFmpeg execution failed: %s", e)

    return False


class VideoConverter:
    """Orchestrates non-blocking video downloading and low-memory transcoding."""

    def __init__(
        self,
        max_height: int | None = None,
        scratch_dir: Path | None = None,
    ) -> None:
        self.max_height = max_height or config.max_video_height
        self.scratch_dir = scratch_dir or Path(config.temp_dir)

    @staticmethod
    def _sanitize_title(title: str, index: int) -> str:
        """Create a filesystem-friendly name for the transcoded video."""
        clean = re.sub(r'[^a-zA-Z0-9_\-]', '_', title).strip('_')
        if not clean:
            clean = f"video_{index:03d}"
        return f"{index:03d}_{clean[:40]}.webm"

    async def process_video(
        self,
        url: str,
        output_dir: Path,
        index: int,
    ) -> Path | None:
        """Download and transcode a single video URL to .webm."""
        output_dir.mkdir(parents=True, exist_ok=True)
        raw_download: Path | None = None

        async with _TRANSCODE_LOCK:
            try:
                # 1. Download video with yt-dlp in worker thread
                raw_download = await asyncio.to_thread(
                    _download_video_sync,
                    url,
                    output_dir,
                    index,
                    self.max_height,
                )

                if not raw_download or not raw_download.exists():
                    logger.warning("Video download produced no output for %s", url)
                    return None

                # 2. Derive output WebM filename
                output_filename = self._sanitize_title(raw_download.stem, index)
                target_webm_path = output_dir / output_filename

                # 3. Transcode to WebM via FFmpeg in worker thread
                success = await asyncio.to_thread(
                    _transcode_to_webm_sync,
                    raw_download,
                    target_webm_path,
                )

                if success and target_webm_path.exists():
                    logger.info("Successfully converted video to %s", target_webm_path.name)
                    return target_webm_path

            except Exception as e:
                logger.error("Error processing video %s: %s", url, e)

            finally:
                # Guarantee intermediate raw download removal
                if raw_download and raw_download.exists():
                    try:
                        raw_download.unlink(missing_ok=True)
                    except Exception as e:
                        logger.warning("Failed to clean raw video %s: %s", raw_download, e)

        return None

    async def convert_all(
        self,
        urls: list[str],
        output_dir: Path,
    ) -> list[Path]:
        """Sequentially process video URLs and return paths of converted .webm files."""
        results: list[Path] = []
        for i, url in enumerate(urls):
            res = await self.process_video(url, output_dir, i + 1)
            if res:
                results.append(res)
        return results
