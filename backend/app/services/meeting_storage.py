"""
Audio upload + duration probe for meetings.

* ``save_audio_stream`` — reads ``request.stream`` (or any binary file-like
  object) in 1 MB chunks, writing to
  ``<UPLOAD_FOLDER>/meetings/<user_id>/<meeting_id>.<ext>``. Enforces the
  configured byte cap (``MEETING_MAX_AUDIO_BYTES``) and cleans up the
  partial file if the cap is hit or any IO error fires.
* ``probe_duration_seconds`` — best-effort ffprobe shell-out, returns
  ``None`` on any failure (missing binary, non-zero exit, unparsable
  output).

The streaming variant lets the route bypass Flask's
``MAX_CONTENT_LENGTH=16MB`` cap without touching the global config — the
upload endpoint reads the raw request body itself.
"""
from __future__ import annotations

import logging
import mimetypes
import os
import subprocess
from pathlib import Path
from typing import IO, Optional

from app.settings import settings

logger = logging.getLogger(__name__)


_CHUNK_SIZE = 1024 * 1024  # 1 MB

_CONTENT_TYPE_TO_EXT = {
    'audio/webm': '.webm',
    'audio/ogg': '.ogg',
    'audio/mpeg': '.mp3',
    'audio/mp3': '.mp3',
    'audio/wav': '.wav',
    'audio/x-wav': '.wav',
    'audio/wave': '.wav',
    'audio/mp4': '.m4a',
    'audio/x-m4a': '.m4a',
    'audio/flac': '.flac',
    'audio/x-flac': '.flac',
    'video/webm': '.webm',
    'video/mp4': '.mp4',
}

_ALLOWED_EXTS = {
    '.webm', '.ogg', '.mp3', '.wav', '.m4a', '.flac', '.mp4', '.mpga', '.oga',
}


class AudioTooLargeError(Exception):
    """Streamed payload exceeded ``MEETING_MAX_AUDIO_BYTES``."""


def _resolve_extension(
    *,
    content_type: str | None,
    filename: str | None,
) -> str:
    """Best-effort extension picker — port of upstream ``_resolve_extension``
    targeting plain string inputs instead of FastAPI's ``UploadFile``.

    Resolution order:
      1. Explicit Content-Type → known mapping.
      2. Content-Type → ``mimetypes.guess_extension`` if it lands in the
         allow-list.
      3. Filename suffix (lower-cased) if in allow-list.
      4. ``.webm`` fallback (matches getDisplayMedia/getUserMedia default).
    """
    ct = (content_type or '').lower()
    if ct in _CONTENT_TYPE_TO_EXT:
        return _CONTENT_TYPE_TO_EXT[ct]

    if ct:
        guessed = mimetypes.guess_extension(ct)
        if guessed and guessed.lower() in _ALLOWED_EXTS:
            return guessed.lower()

    if filename:
        suffix = Path(filename).suffix.lower()
        if suffix in _ALLOWED_EXTS:
            return suffix

    return '.webm'


def _meetings_root() -> Path:
    upload_folder = settings.get('UPLOAD_FOLDER', 'uploads')
    subdir = settings.get('MEETING_UPLOAD_SUBDIR', 'meetings')
    return Path(upload_folder).resolve() / subdir


def _max_bytes() -> int:
    cap = settings.get('MEETING_MAX_AUDIO_BYTES')
    if isinstance(cap, int) and cap > 0:
        return cap
    return 500 * 1024 * 1024  # safety default


def save_audio_stream(
    stream: IO[bytes],
    *,
    meeting_id: str,
    user_id: str,
    content_type: str | None,
    filename: str | None,
    max_bytes: int | None = None,
) -> tuple[str, str, int]:
    """Stream a binary file-like object to disk in 1 MB chunks.

    Returns ``(absolute_path, resolved_extension_without_dot, bytes_written)``.

    Raises:
        AudioTooLargeError: payload exceeded the configured cap. The partial
            file is removed before raising.
        OSError: filesystem failure. The partial file is removed before
            re-raising.
    """
    cap = max_bytes if max_bytes is not None else _max_bytes()
    root = _meetings_root() / str(user_id)
    root.mkdir(parents=True, exist_ok=True)

    ext = _resolve_extension(content_type=content_type, filename=filename)
    target = root / f"{meeting_id}{ext}"

    written = 0
    try:
        with target.open('wb') as out:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                written += len(chunk)
                if written > cap:
                    raise AudioTooLargeError(
                        f"audio exceeds {cap} bytes (read {written})"
                    )
                out.write(chunk)
    except AudioTooLargeError:
        _unlink_quiet(target)
        raise
    except Exception:
        _unlink_quiet(target)
        raise

    return str(target), ext.lstrip('.'), written


def _unlink_quiet(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError as exc:  # pragma: no cover - best-effort cleanup
        logger.warning("failed to remove partial audio %s: %s", path, exc)


def probe_duration_seconds(path: str | os.PathLike) -> Optional[float]:
    """ffprobe-based duration probe. Returns ``None`` on any failure.

    Mirrors the FastAPI app verbatim: no exception escapes — callers should
    treat ``None`` as "duration unknown".
    """
    try:
        completed = subprocess.run(
            [
                'ffprobe',
                '-v',
                'error',
                '-show_entries',
                'format=duration',
                '-of',
                'default=nw=1:nk=1',
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ffprobe unexpected failure: %s", exc)
        return None

    raw = (completed.stdout or '').strip()
    if not raw or raw.upper() == 'N/A':
        return None
    try:
        return float(raw)
    except ValueError:
        return None
