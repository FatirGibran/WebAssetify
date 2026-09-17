"""Tests for standalone CLI module."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from cli import build_parser, parse_input_source, run_pipeline


def test_build_parser():
    parser = build_parser()
    args = parser.parse_args(["my_doc.pdf", "-o", "./custom_out", "--zip", "-q", "90"])
    assert args.source == "my_doc.pdf"
    assert args.output == "./custom_out"
    assert args.zip is True
    assert args.quality == 90


def test_cli_version(capsys):
    parser = build_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "1.1.0" in captured.out or "1.1.0" in captured.err


def test_parse_input_source_file(tmp_path: Path):
    doc_file = tmp_path / "sample.html"
    doc_file.write_text('<a href="https://example.com/asset.png">Download</a>', encoding="utf-8")
    urls = parse_input_source(str(doc_file))
    assert "https://example.com/asset.png" in urls


def test_parse_input_source_raw_string():
    raw = "Visit https://example.com/image.jpg and https://example.com/other.webp"
    urls = parse_input_source(raw)
    assert len(urls) == 2
    assert "https://example.com/image.jpg" in urls


@pytest.mark.asyncio
async def test_run_pipeline_local_zip_and_manifest(tmp_path: Path):
    out_dir = tmp_path / "cli_output"
    source = "No URLs here"
    result = await run_pipeline(
        source=source,
        output_dir=out_dir,
        quality=80,
        max_dimension=1000,
        max_video_height=720,
        create_zip=True,
        upload_drive=False,
    )
    assert result["success"] is False
    assert result["message"] == "No URLs found"
