"""Tests for image and video converters."""

import io
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PIL import Image

from converters.image_converter import ImageConverter, _process_image_to_webp
from converters.video_converter import VideoConverter, _transcode_to_webm_sync


def test_process_image_to_webp(tmp_path: Path):
    # Create test image in memory
    img = Image.new("RGB", (100, 100), color="blue")
    img_byte_arr = io.BytesIO()
    img.save(img_byte_arr, format="PNG")
    raw_bytes = img_byte_arr.getvalue()

    output_webp = tmp_path / "output.webp"
    success = _process_image_to_webp(raw_bytes, output_webp, quality=80)

    assert success is True
    assert output_webp.exists()
    assert output_webp.stat().st_size > 0

    # Verify it can be opened as WEBP
    with Image.open(output_webp) as loaded_img:
        assert loaded_img.format == "WEBP"
        assert loaded_img.size == (100, 100)


def test_image_converter_filename_generation():
    name1 = ImageConverter._generate_filename("https://example.com/images/hero-banner.png", 1)
    assert name1 == "001_hero-banner.webp"

    name2 = ImageConverter._generate_filename("https://example.com/download?id=123", 2)
    assert name2.startswith("image_002_")
    assert name2.endswith(".webp")


def test_video_converter_sanitize_title():
    title = VideoConverter._sanitize_title("My Super Video [2026]!! (HD)", 1)
    assert title.endswith(".webm")
    assert "!" not in title
    assert "[" not in title


@patch("subprocess.run")
def test_transcode_to_webm_cli_arguments(mock_run, tmp_path: Path):
    # Mock subprocess.run
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

    input_file = tmp_path / "input.mp4"
    input_file.write_bytes(b"dummy video content")
    output_file = tmp_path / "output.webm"
    output_file.write_bytes(b"dummy webm content")

    success = _transcode_to_webm_sync(input_file, output_file)
    assert success is True

    # Assert subprocess.run called with exact low-memory arguments
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert cmd[0] == "ffmpeg"
    assert "-c:v" in cmd and "libvpx-vp9" in cmd
    assert "-crf" in cmd and "32" in cmd
    assert "-threads" in cmd and "1" in cmd
    assert "-speed" in cmd and "4" in cmd
    assert "-c:a" in cmd and "libopus" in cmd
