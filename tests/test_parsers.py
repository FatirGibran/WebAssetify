"""Tests for document parsers (universal, PDF, DOCX)."""

import io
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE
import pypdf
from pypdf.generic import ArrayObject, DictionaryObject, NameObject, TextStringObject

from parsers.universal import (
    classify_urls,
    clean_url,
    extract_urls,
    extract_urls_from_json,
    extract_urls_from_tabular,
    is_image_url,
    is_video_url,
)
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.docx_parser import extract_urls_from_docx
from parsers.html_parser import extract_urls_from_html


def test_clean_url():
    assert clean_url("https://example.com/image.png.") == "https://example.com/image.png"
    assert clean_url("www.example.com/test,") == "https://www.example.com/test"
    assert clean_url("https://example.com/page)") == "https://example.com/page"


def test_extract_urls_markdown_and_raw():
    sample_text = """
    # Project Title
    Check our website: https://example.com/about.
    Here is an image: ![Hero Banner](https://example.com/assets/hero.jpg)
    Also view our [Demo Video](https://www.youtube.com/watch?v=dQw4w9WgXcQ).
    Duplicate link: https://example.com/about
    """
    urls = extract_urls(sample_text)
    assert len(urls) == 3
    assert "https://example.com/assets/hero.jpg" in urls
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in urls
    assert "https://example.com/about" in urls


def test_classify_urls():
    urls = [
        "https://example.com/banner.png",
        "https://example.com/photo.jpeg?format=webp",
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://vimeo.com/12345678",
        "https://example.com/clip.mp4",
        "https://example.com/article/read-more",
    ]
    classified = classify_urls(urls)
    assert "https://example.com/banner.png" in classified["images"]
    assert "https://example.com/photo.jpeg?format=webp" in classified["images"]
    assert "https://www.youtube.com/watch?v=dQw4w9WgXcQ" in classified["videos"]
    assert "https://vimeo.com/12345678" in classified["videos"]
    assert "https://example.com/clip.mp4" in classified["videos"]
    assert "https://example.com/article/read-more" in classified["others"]


def test_pdf_parser_text_and_annots():
    # Build a synthetic PDF with text and annotations
    writer = pypdf.PdfWriter()
    page = writer.add_blank_page(width=300, height=300)

    # Add URI annotation
    annot_dict = DictionaryObject({
        NameObject("/Type"): NameObject("/Annot"),
        NameObject("/Subtype"): NameObject("/Link"),
        NameObject("/A"): DictionaryObject({
            NameObject("/S"): NameObject("/URI"),
            NameObject("/URI"): TextStringObject("https://example.com/annotated-link.jpg"),
        }),
    })
    page[NameObject("/Annots")] = ArrayObject([annot_dict])

    pdf_stream = io.BytesIO()
    writer.write(pdf_stream)
    pdf_bytes = pdf_stream.getvalue()

    urls = extract_urls_from_pdf(pdf_bytes)
    assert "https://example.com/annotated-link.jpg" in urls


def test_docx_parser_text_and_hyperlinks():
    # Build a synthetic DOCX in-memory
    doc = Document()
    doc.add_paragraph("Visit https://example.com/direct-in-para.png for assets.")

    # Add table with link
    table = doc.add_table(rows=1, cols=1)
    table.rows[0].cells[0].text = "Table URL: https://example.com/table-image.png"

    # Add XML relationship hyperlink
    doc.part.relate_to(
        "https://example.com/xml-hyperlink.png",
        RELATIONSHIP_TYPE.HYPERLINK,
        is_external=True,
    )

    docx_stream = io.BytesIO()
    doc.save(docx_stream)
    docx_bytes = docx_stream.getvalue()

    urls = extract_urls_from_docx(docx_bytes)
    assert "https://example.com/direct-in-para.png" in urls
    assert "https://example.com/table-image.png" in urls
    assert "https://example.com/xml-hyperlink.png" in urls


def test_html_parser_extracts_all_tags():
    sample_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <link rel="icon" href="https://example.com/favicon.ico">
        <style>
            .banner { background-image: url('https://example.com/css-bg.png'); }
        </style>
    </head>
    <body>
        <a href="https://example.com/link-target">Click</a>
        <img src="https://example.com/main.jpg" data-src="https://example.com/lazy.jpg"
             srcset="https://example.com/small.jpg 300w, https://example.com/large.jpg 800w">
        <video src="https://example.com/video.mp4" poster="https://example.com/poster.jpg">
            <source src="https://example.com/source.webm" type="video/webm">
        </video>
        <iframe src="https://www.youtube.com/embed/dQw4w9WgXcQ"></iframe>
        <div style="background-image: url(https://example.com/inline-style.png)"></div>
        <p>Direct text link: https://example.com/in-text-paragraph</p>
    </body>
    </html>
    """
    urls = extract_urls_from_html(sample_html)
    assert "https://example.com/favicon.ico" in urls
    assert "https://example.com/css-bg.png" in urls
    assert "https://example.com/link-target" in urls
    assert "https://example.com/main.jpg" in urls
    assert "https://example.com/lazy.jpg" in urls
    assert "https://example.com/small.jpg" in urls
    assert "https://example.com/large.jpg" in urls
    assert "https://example.com/video.mp4" in urls
    assert "https://example.com/poster.jpg" in urls
    assert "https://example.com/source.webm" in urls
    assert "https://www.youtube.com/embed/dQw4w9WgXcQ" in urls
    assert "https://example.com/inline-style.png" in urls
    assert "https://example.com/in-text-paragraph" in urls


def test_tabular_parser_csv_and_tsv():
    csv_data = """id,name,asset_url,preview
1,Item A,https://example.com/item1.png,https://example.com/preview1.jpg
2,Item B,https://example.com/item2.png,https://example.com/preview2.jpg
"""
    urls = extract_urls_from_tabular(csv_data)
    assert len(urls) == 4
    assert "https://example.com/item1.png" in urls
    assert "https://example.com/preview2.jpg" in urls

    tsv_data = "col1\tcol2\nval\thttps://example.com/tsv-asset.webp\n"
    tsv_urls = extract_urls_from_tabular(tsv_data)
    assert "https://example.com/tsv-asset.webp" in tsv_urls


def test_json_parser():
    json_data = """
    {
        "project": "WebAssetify",
        "assets": [
            {"type": "image", "url": "https://example.com/json-img1.png"},
            {"type": "video", "url": "https://example.com/json-vid1.mp4"}
        ],
        "metadata": {
            "thumbnail": "https://example.com/thumb.jpg"
        }
    }
    """
    urls = extract_urls_from_json(json_data)
    assert "https://example.com/json-img1.png" in urls
    assert "https://example.com/json-vid1.mp4" in urls
    assert "https://example.com/thumb.jpg" in urls

