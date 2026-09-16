"""Google Drive storage integration using Drive API v3.

Authenticates via Service Account, creates structured folders, uploads WebP/WebM assets,
packages assets into an assets_bundle.zip, and shares the folder publicly with viewer access.
All synchronous Google API calls are wrapped in asyncio.to_thread to honor async discipline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.oauth2 import service_account
from googleapiclient.discovery import Resource, build
from googleapiclient.http import MediaFileUpload

from config import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive"]

MIME_FOLDER = "application/vnd.google-apps.folder"
MIME_ZIP = "application/zip"
MIME_WEBP = "image/webp"
MIME_WEBM = "video/webm"
MIME_JSON = "application/json"
MIME_TEXT = "text/plain"


def _create_bundle_zip_sync(scratch_dir: Path, zip_output_path: Path) -> Path:
    """Synchronously compress images and videos subdirectories into a zip archive."""
    zip_output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_output_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for sub_name in ("images", "videos"):
            sub_dir = scratch_dir / sub_name
            if sub_dir.is_dir():
                for file_path in sub_dir.iterdir():
                    if file_path.is_file():
                        # Store in archive as images/filename or videos/filename
                        arcname = f"{sub_name}/{file_path.name}"
                        zipf.write(file_path, arcname=arcname)

        # Include session manifest and summary if present
        for report_file in ("manifest.json", "session_summary.txt"):
            rf_path = scratch_dir / report_file
            if rf_path.is_file():
                zipf.write(rf_path, arcname=report_file)

    return zip_output_path


class GoogleDriveStorage:
    """Async wrapper around Google Drive API v3 for asset delivery."""

    def __init__(
        self,
        service_account_source: str | None = None,
        parent_folder_id: str | None = None,
    ) -> None:
        self.sa_source = (
            service_account_source
            if service_account_source is not None
            else config.gdrive_service_account_json
        )
        self.parent_folder_id = (
            parent_folder_id
            if parent_folder_id is not None
            else config.gdrive_parent_folder_id
        )
        self._service: Resource | None = None

    def _get_service(self) -> Resource:
        """Initialize Google Drive service client synchronously."""
        if self._service is not None:
            return self._service

        if not self.sa_source:
            raise ValueError(
                "Google Drive Service Account configuration is missing. "
                "Set GDRIVE_SERVICE_ACCOUNT_JSON in environment."
            )

        source = self.sa_source.strip()
        credentials: service_account.Credentials

        # Check if source points to an existing file
        if Path(source).is_file():
            credentials = service_account.Credentials.from_service_account_file(
                source, scopes=SCOPES
            )
        else:
            # Parse as JSON string
            try:
                info = json.loads(source)
                credentials = service_account.Credentials.from_service_account_info(
                    info, scopes=SCOPES
                )
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"GDRIVE_SERVICE_ACCOUNT_JSON is neither a valid JSON string nor an existing file path: {e}"
                ) from e

        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        return self._service

    def _create_folder_sync(self, folder_name: str, parent_id: str) -> dict[str, str]:
        """Synchronously create a folder in Google Drive."""
        service = self._get_service()
        file_metadata = {
            "name": folder_name,
            "mimeType": MIME_FOLDER,
            "parents": [parent_id] if parent_id else [],
        }
        folder = (
            service.files()
            .create(
                body=file_metadata,
                fields="id, name, webViewLink",
                supportsAllDrives=True,
            )
            .execute()
        )
        logger.info("Created Drive folder: %s (ID: %s)", folder.get("name"), folder.get("id"))
        return folder

    def _upload_file_sync(
        self,
        file_path: Path,
        parent_id: str,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Synchronously upload a single file with resumable chunking."""
        service = self._get_service()

        if mime_type is None:
            ext = file_path.suffix.lower()
            if ext == ".webp":
                mime_type = MIME_WEBP
            elif ext == ".webm":
                mime_type = MIME_WEBM
            elif ext == ".zip":
                mime_type = MIME_ZIP
            elif ext == ".json":
                mime_type = MIME_JSON
            elif ext in (".txt", ".log", ".md"):
                mime_type = MIME_TEXT
            else:
                mime_type = "application/octet-stream"

        file_metadata = {
            "name": file_path.name,
            "parents": [parent_id],
        }

        media = MediaFileUpload(
            str(file_path),
            mimetype=mime_type,
            resumable=True,
            chunksize=1024 * 1024 * 2,  # 2MB chunks for memory efficiency
        )

        uploaded_file = (
            service.files()
            .create(
                body=file_metadata,
                media_body=media,
                fields="id, name, webViewLink, size",
                supportsAllDrives=True,
            )
            .execute()
        )
        logger.info("Uploaded to Drive: %s (ID: %s)", file_path.name, uploaded_file.get("id"))
        return uploaded_file

    def _share_folder_public_sync(self, folder_id: str) -> None:
        """Synchronously grant viewer access to anyone with the link."""
        service = self._get_service()
        permission = {
            "type": "anyone",
            "role": "reader",
        }
        service.permissions().create(
            fileId=folder_id,
            body=permission,
            fields="id",
            supportsAllDrives=True,
        ).execute()
        logger.info("Public viewer permission granted for folder ID: %s", folder_id)

    async def create_folder(self, folder_name: str, parent_id: str) -> dict[str, str]:
        """Asynchronously create a Google Drive folder."""
        return await asyncio.to_thread(self._create_folder_sync, folder_name, parent_id)

    async def upload_file(
        self,
        file_path: Path,
        parent_id: str,
        mime_type: str | None = None,
    ) -> dict[str, Any]:
        """Asynchronously upload a file to a Google Drive folder."""
        return await asyncio.to_thread(
            self._upload_file_sync, file_path, parent_id, mime_type
        )

    async def share_folder_public(self, folder_id: str) -> None:
        """Asynchronously make a folder viewable by anyone with the link."""
        await asyncio.to_thread(self._share_folder_public_sync, folder_id)

    async def upload_pipeline(
        self,
        scratch_dir: Path,
        user_id: int | str,
        session_stats: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run the full Google Drive upload workflow for a processed batch.

        1. Creates root folder: WebAssetify_{Timestamp}_{user_id}
        2. Creates 'images' and 'videos' subfolders and uploads contents.
        3. Generates manifest.json and session_summary.txt.
        4. Creates assets_bundle.zip (including manifest) and uploads it to root folder.
        5. Uploads manifest.json and session_summary.txt to root folder.
        6. Shares root folder with anyone as reader.
        7. Returns webViewLink and asset statistics.
        """
        if not self.parent_folder_id:
            raise ValueError("GDRIVE_PARENT_FOLDER_ID is required for upload.")

        now_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        root_folder_name = f"WebAssetify_{now_str}_{user_id}"

        # 1. Create root folder
        root_folder = await self.create_folder(root_folder_name, self.parent_folder_id)
        root_folder_id = root_folder["id"]

        images_count = 0
        videos_count = 0

        # 2. Upload images if any
        images_dir = scratch_dir / "images"
        if images_dir.is_dir():
            image_files = [p for p in images_dir.iterdir() if p.is_file()]
            if image_files:
                images_subfolder = await self.create_folder("images", root_folder_id)
                for img in image_files:
                    await self.upload_file(img, images_subfolder["id"], MIME_WEBP)
                    images_count += 1

        # 3. Upload videos if any
        videos_dir = scratch_dir / "videos"
        if videos_dir.is_dir():
            video_files = [p for p in videos_dir.iterdir() if p.is_file()]
            if video_files:
                videos_subfolder = await self.create_folder("videos", root_folder_id)
                for vid in video_files:
                    await self.upload_file(vid, videos_subfolder["id"], MIME_WEBM)
                    videos_count += 1

        # 4. Generate manifest.json and session_summary.txt
        manifest_data = {
            "service": "WebAssetify",
            "timestamp": now_str,
            "user_id": str(user_id),
            "images_count": images_count,
            "videos_count": videos_count,
            "savings": session_stats or {},
        }
        manifest_path = scratch_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

        summary_text = (
            f"WebAssetify Session Report\n"
            f"==========================\n"
            f"Timestamp: {now_str}\n"
            f"User ID: {user_id}\n"
            f"Optimized Images: {images_count}\n"
            f"Transcoded Videos: {videos_count}\n"
        )
        if session_stats:
            orig_mb = session_stats.get("original_bytes", 0) / (1024 * 1024)
            conv_mb = session_stats.get("converted_bytes", 0) / (1024 * 1024)
            saved_mb = session_stats.get("saved_bytes", 0) / (1024 * 1024)
            pct = session_stats.get("saved_percentage", 0.0)
            summary_text += (
                f"Original Size: {orig_mb:.2f} MB\n"
                f"Optimized Size: {conv_mb:.2f} MB\n"
                f"Storage Saved: {saved_mb:.2f} MB ({pct:.1f}%)\n"
            )
        summary_path = scratch_dir / "session_summary.txt"
        summary_path.write_text(summary_text, encoding="utf-8")

        # 5. Create and upload assets_bundle.zip to root folder
        zip_path = scratch_dir / "assets_bundle.zip"
        await asyncio.to_thread(_create_bundle_zip_sync, scratch_dir, zip_path)

        if zip_path.exists() and zip_path.stat().st_size > 0:
            await self.upload_file(zip_path, root_folder_id, MIME_ZIP)

        # 6. Upload manifest and summary directly to root folder
        await self.upload_file(manifest_path, root_folder_id, MIME_JSON)
        await self.upload_file(summary_path, root_folder_id, MIME_TEXT)

        # 7. Make root folder publicly readable
        await self.share_folder_public(root_folder_id)

        # 8. Retrieve latest webViewLink
        web_view_link = root_folder.get("webViewLink")
        if not web_view_link:
            web_view_link = f"https://drive.google.com/drive/folders/{root_folder_id}"

        return {
            "folder_id": root_folder_id,
            "folder_name": root_folder_name,
            "web_view_link": web_view_link,
            "images_count": images_count,
            "videos_count": videos_count,
            "has_bundle": zip_path.exists(),
            "manifest_created": manifest_path.exists(),
        }
