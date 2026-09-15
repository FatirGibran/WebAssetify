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
    is_image_url,
    is_video_url,
)
from parsers.pdf_parser import extract_urls_from_pdf
from parsers.docx_parser import extract_urls_from_docx


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
