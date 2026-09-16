"""Tests for Google Drive storage integration."""

import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from storage.gdrive import GoogleDriveStorage, _create_bundle_zip_sync


def test_create_bundle_zip_sync(tmp_path: Path):
    scratch = tmp_path / "scratch"
    images_dir = scratch / "images"
    videos_dir = scratch / "videos"
    images_dir.mkdir(parents=True)
    videos_dir.mkdir(parents=True)

    img1 = images_dir / "001_photo.webp"
    img1.write_bytes(b"dummy webp")
    vid1 = videos_dir / "001_clip.webm"
    vid1.write_bytes(b"dummy webm")

    zip_out = scratch / "assets_bundle.zip"
    result = _create_bundle_zip_sync(scratch, zip_out)

    assert result.exists()
    assert result == zip_out

    with zipfile.ZipFile(zip_out, "r") as zf:
        namelist = zf.namelist()
        assert "images/001_photo.webp" in namelist
        assert "videos/001_clip.webm" in namelist


def test_gdrive_storage_missing_credentials():
    storage = GoogleDriveStorage(service_account_source="", parent_folder_id="parent123")
    with pytest.raises(ValueError, match="Service Account configuration is missing"):
        storage._get_service()


def test_gdrive_storage_invalid_json():
    storage = GoogleDriveStorage(service_account_source="not-a-valid-json", parent_folder_id="parent123")
    with pytest.raises(ValueError, match="neither a valid JSON string nor an existing file path"):
        storage._get_service()


@pytest.mark.asyncio
async def test_upload_pipeline(tmp_path: Path):
    scratch = tmp_path / "scratch"
    images_dir = scratch / "images"
    videos_dir = scratch / "videos"
    images_dir.mkdir(parents=True)
    videos_dir.mkdir(parents=True)

    (images_dir / "001_hero.webp").write_bytes(b"img")
    (videos_dir / "001_demo.webm").write_bytes(b"vid")

    storage = GoogleDriveStorage(
        service_account_source='{"type": "service_account"}',
        parent_folder_id="parent_root",
    )

    # Mock internal methods so no real network requests occur
    with (
        patch.object(storage, "create_folder") as mock_create_folder,
        patch.object(storage, "upload_file") as mock_upload_file,
        patch.object(storage, "share_folder_public") as mock_share,
    ):
        mock_create_folder.side_effect = [
            {"id": "root_folder_id", "name": "WebAssetify_test", "webViewLink": "https://drive.google.com/folders/root"},
            {"id": "images_subfolder_id", "name": "images"},
            {"id": "videos_subfolder_id", "name": "videos"},
        ]
        mock_upload_file.return_value = {"id": "uploaded_file_id"}
        mock_share.return_value = None

        sample_stats = {
            "original_bytes": 1000,
            "converted_bytes": 400,
            "saved_bytes": 600,
            "saved_percentage": 60.0,
        }
        result = await storage.upload_pipeline(scratch, user_id=12345, session_stats=sample_stats)

        assert result["folder_id"] == "root_folder_id"
        assert result["web_view_link"] == "https://drive.google.com/folders/root"
        assert result["images_count"] == 1
        assert result["videos_count"] == 1
        assert result["has_bundle"] is True
        assert result["manifest_created"] is True

        assert mock_create_folder.call_count == 3  # root, images, videos
        assert mock_upload_file.call_count == 5  # 1 img, 1 vid, 1 bundle zip, 1 manifest.json, 1 session_summary.txt
        mock_share.assert_called_once_with("root_folder_id")
