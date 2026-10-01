"""Filesystem helpers. ``secure_filename`` is a faithful reimplementation of
``werkzeug.utils.secure_filename`` (werkzeug was removed together with Flask)."""
from __future__ import annotations

import os
import re
import unicodedata

_filename_ascii_strip_re = re.compile(r"[^A-Za-z0-9_.-]")
_windows_device_files = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(10)),
    *(f"LPT{i}" for i in range(10)),
}


def display_filename(filename: str) -> str:
    """A human-facing filename: traversal-free but UNICODE-PRESERVING.

    ``secure_filename`` is ASCII-only by (werkzeug) design, which collapses
    Persian names like ``فروش_بهار.csv`` to ``csv`` — unacceptable for
    ``uploads.original_name``, which is display + download-filename only (the
    on-disk name is always a generated ``<uuid>.<ext>``). Strip directory
    parts, control chars and Windows-reserved punctuation; keep everything
    else (Starlette RFC 5987-encodes non-ASCII in Content-Disposition).
    """
    base = os.path.basename(filename or "").strip()
    base = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", base)
    base = "_".join(base.split()).strip("._") or "file"
    if (
        os.name == "nt"
        and base.split(".")[0].upper() in _windows_device_files
    ):
        base = f"_{base}"
    return base[:255]


def secure_filename(filename: str) -> str:
    """Return a filename safe to store on a regular filesystem.

    Strips directory components + non-ASCII, collapses whitespace to single
    underscores, and prefixes Windows device names — matching werkzeug's
    behaviour so existing upload paths are unchanged.
    """
    filename = unicodedata.normalize("NFKD", filename)
    filename = filename.encode("ascii", "ignore").decode("ascii")
    for sep in os.sep, os.altsep:
        if sep:
            filename = filename.replace(sep, " ")
    filename = str(_filename_ascii_strip_re.sub("", "_".join(filename.split()))).strip("._")
    if (
        os.name == "nt"
        and filename
        and filename.split(".")[0].upper() in _windows_device_files
    ):
        filename = f"_{filename}"
    return filename


__all__ = ["secure_filename", "display_filename"]
