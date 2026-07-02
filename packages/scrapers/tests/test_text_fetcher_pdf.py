"""Tests for PDF text extraction in the text fetcher."""

from __future__ import annotations

import io

from pypdf import PdfWriter

from axiom_bills._common.text_fetcher import _to_text


def test_corrupt_pdf_returns_none():
    assert _to_text("pdf", b"not a pdf at all") is None


def test_blank_pdf_returns_none():
    buf = io.BytesIO()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    w.write(buf)
    assert _to_text("pdf", buf.getvalue()) is None


def test_html_still_extracts():
    assert _to_text("html", b"<p>Section 32 is amended</p>") == "Section 32 is amended"
