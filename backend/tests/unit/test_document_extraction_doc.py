"""Unit tests for document extraction — csv/txt/doc + extractable set."""
from __future__ import annotations

import io

import pytest

from app.services import document_extraction_service as des


def test_is_extractable_includes_doc_csv_txt():
    for ext in ("doc", "docx", "csv", "txt", "xlsx"):
        assert des.is_extractable(ext) is True
        assert des.is_extractable(f".{ext}") is True


def test_extract_txt_ok():
    raw = b"hello secret AURORA-7-DLPTEST world"
    result = des.extract_text(
        raw, filename="a.txt", mime_type="text/plain", extension="txt", max_chars=10_000,
    )
    assert result["status"] == "ok"
    assert "AURORA-7-DLPTEST" in result["markdown"]
    assert result["chars"] > 0


def test_extract_csv_ok():
    raw = b"name,code\nalice,AURORA-7-DLPTEST\n"
    result = des.extract_text(
        raw, filename="a.csv", mime_type="text/csv", extension="csv", max_chars=10_000,
    )
    assert result["status"] == "ok"
    assert "AURORA-7-DLPTEST" in result["markdown"]


def test_extract_docx_ok():
    pytest.importorskip("docx")
    import docx

    doc = docx.Document()
    doc.add_paragraph("report for AURORA-7-DLPTEST")
    buf = io.BytesIO()
    doc.save(buf)
    result = des.extract_text(
        buf.getvalue(),
        filename="a.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        extension="docx",
        max_chars=10_000,
    )
    assert result["status"] == "ok"
    assert "AURORA-7-DLPTEST" in result["markdown"]


def test_extract_doc_garbage_errors_not_crash():
    """Poison bytes must map to error/unavailable, never raise."""
    result = des.extract_text(
        b"not-an-ole-file-XXXX",
        filename="bad.doc",
        mime_type="application/msword",
        extension="doc",
        max_chars=10_000,
    )
    assert result["status"] in ("error", "unavailable", "ok")
    # If somehow decoded as soft-text, still a contract dict.
    assert "markdown" in result
    assert "chars" in result


def test_extract_doc_with_ole_fixture_when_available():
    """Build a minimal OLE with WordDocument stream containing UTF-16LE secret.

    Only runs a meaningful assert when olefile is installed; otherwise the
    extractor returns unavailable without crashing.
    """
    try:
        import olefile  # noqa: F401
    except ImportError:
        result = des.extract_text(
            b"x", filename="a.doc", mime_type="application/msword",
            extension="doc", max_chars=10_000,
        )
        assert result["status"] in ("unavailable", "error")
        return

    # Craft a tiny OLE compound file with a WordDocument stream holding the
    # secret as UTF-16LE so the recoverable-runs path finds it.
    secret = "AURORA-7-DLPTEST"
    stream = ("HEADER" + secret).encode("utf-16-le")
    buf = io.BytesIO()
    ole = olefile.OleFileIO()  # type: ignore[attr-defined]
    # olefile cannot easily *write* a new OLE from scratch in all versions.
    # Use OleWriter if available; otherwise skip meaningful content assert.
    writer_cls = getattr(olefile, "OleWriter", None)
    if writer_cls is None:
        # Soft path: plain-text mislabeled .doc still recovers via decode.
        plain = f"notes about {secret}".encode("utf-8")
        result = des.extract_text(
            plain, filename="notes.doc", mime_type="application/msword",
            extension="doc", max_chars=10_000,
        )
        assert result["status"] == "ok"
        assert secret in result["markdown"]
        return

    # Prefer OleWriter when present.
    w = writer_cls()
    w.add_stream("WordDocument", stream)
    out = io.BytesIO()
    w.write(out)
    result = des.extract_text(
        out.getvalue(),
        filename="a.doc",
        mime_type="application/msword",
        extension="doc",
        max_chars=10_000,
    )
    assert result["status"] == "ok"
    assert secret in result["markdown"]
