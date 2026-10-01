"""Uploads router — files, images, video serve, thumbnails.

Mounted at ``/api/uploads``. Shared disk helpers (``_get_upload_folder``,
``_handle_upload``, ``_safe_serve_name``) also used by image_gen.
"""
from __future__ import annotations

import base64
import logging
import mimetypes
import os
import uuid as _uuid

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from app.utils.files import display_filename

from app.api.deps import current_user, flask_ctx, require_active
from app.settings import settings
from app.models.upload import UploadModel
from app.services import document_extraction_service
from app.utils.helpers import serialize_doc

logger = logging.getLogger(__name__)

# Router-level dependency: every request runs inside the Flask app_context.
router = APIRouter(dependencies=[Depends(flask_ctx)])

_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
# Audio/video extensions: stored disk-backed, never text-extracted (the upload
# handler short-circuits these to extraction_status='na'). Mirrors the A/V
# entries added to Config.ALLOWED_EXTENSIONS.
_MEDIA_EXTENSIONS = {
    'mp3', 'wav', 'm4a', 'ogg', 'flac', 'aac', 'aiff',
    'mp4', 'webm', 'mov', 'mpeg', 'mpg',
}

# ---------------------------------------------------------------------------
# Helpers (ported verbatim from app/routes/uploads.py module functions).
# ---------------------------------------------------------------------------
def _allowed_file(filename: str) -> bool:
    allowed = settings.get(
        'ALLOWED_EXTENSIONS',
        {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'txt', 'md', 'zip'},
    )
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def _get_upload_folder() -> str:
    folder = settings.get('UPLOAD_FOLDER', 'uploads')
    if not os.path.exists(folder):
        os.makedirs(folder)
    return folder


def _create_thumbnail(image_path: str, thumbnail_path: str, size=(200, 200)) -> bool:
    try:
        from PIL import Image

        with Image.open(image_path) as img:
            img.thumbnail(size)
            img.save(thumbnail_path)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("create_thumbnail failed: %s", exc)
        return False


def _safe_serve_name(name: str) -> str | None:
    """Return ``name`` iff it is a single, traversal-free path component.

    ``send_from_directory`` already blocks traversal; we re-assert it here so a
    crafted DB row (or any path separator / ``..``) can never escape
    ``UPLOAD_FOLDER`` when handed to Starlette's ``FileResponse``.
    """
    if not name:
        return None
    if name != os.path.basename(name) or name in {'.', '..'}:
        return None
    if '/' in name or '\\' in name or os.path.isabs(name):
        return None
    return name


# Mime -> file-extension map for images decoded out of a ZIP (where the only
# type signal is the entry's sniffed mime). Falls back to ``mimetypes`` then png.
_IMAGE_MIME_EXT = {
    'image/png': 'png',
    'image/jpeg': 'jpg',
    'image/jpg': 'jpg',
    'image/gif': 'gif',
    'image/webp': 'webp',
}


def _ext_for_image_mime(mime: str | None) -> str:
    """Best-effort image file extension for a sniffed mime type."""
    if mime:
        mapped = _IMAGE_MIME_EXT.get(mime.lower())
        if mapped:
            return mapped
        guessed = mimetypes.guess_extension(mime)
        if guessed:
            return guessed.lstrip('.').lower()
    return 'png'


def _handle_upload(file: UploadFile, user_id: str, request: Request):
    """Shared multipart-upload handler — the FastAPI port of ``upload_file``.

    Validates the part, sniffs the content type, writes the spooled bytes to
    disk, builds the thumbnail, persists the row, and returns the legacy 201
    payload. ``upload_image`` reuses this after its own image-extension gate.
    """
    if file is None or file.filename is None or file.filename == '':
        return JSONResponse({'error': 'No file selected'}, status_code=400)

    if not _allowed_file(file.filename):
        return JSONResponse({'error': 'File type not allowed'}, status_code=400)

    # Generate unique filename. ``display_filename`` keeps unicode (Persian
    # names) — the on-disk name below is a generated uuid, so original_name is
    # display + Content-Disposition only.
    original_name = display_filename(file.filename)
    extension = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    unique_filename = f"{_uuid.uuid4().hex}.{extension}"

    # Save file — Starlette's UploadFile.file is a sync SpooledTemporaryFile.
    upload_folder = _get_upload_folder()
    file_path = os.path.join(upload_folder, unique_filename)
    src = file.file
    try:
        src.seek(0)
    except Exception:  # noqa: BLE001
        pass

    # Enforce the byte cap during the chunked write so an oversized stream never
    # fully lands on disk. On overflow we delete the partial file and return 413
    # (mirrors meeting_storage.save_audio_stream's overflow→unlink pattern).
    max_bytes = settings.get('CHAT_UPLOAD_MAX_BYTES', 32 * 1024 * 1024)
    written = 0
    too_large = False
    with open(file_path, 'wb') as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_bytes:
                too_large = True
                break
            dst.write(chunk)

    if too_large:
        try:
            os.remove(file_path)
        except OSError as exc:  # noqa: BLE001 - best-effort cleanup
            logger.warning("upload: failed to remove oversized partial: %s", exc)
        return JSONResponse({
            'error': 'File too large',
            'code': 'file_too_large',
            'max_bytes': max_bytes,
        }, status_code=413)

    file_size = os.path.getsize(file_path)

    # Determine declared file type.
    file_type = 'image' if extension in _IMAGE_EXTENSIONS else 'file'

    # Sniff actual content type.
    import filetype

    kind = filetype.guess(file_path)
    sniffed_mime = kind.mime if kind else None
    sniffed_is_image = sniffed_mime is not None and sniffed_mime.startswith('image/')

    # Reject if declared extension contradicts sniffed content.
    if file_type == 'image' and sniffed_mime is not None and not sniffed_is_image:
        os.remove(file_path)
        return JSONResponse({'error': 'mime_mismatch'}, status_code=400)
    if file_type != 'image' and sniffed_is_image:
        os.remove(file_path)
        return JSONResponse({'error': 'mime_mismatch'}, status_code=400)

    # Non-images serve as attachments (prevent inline XSS via HTML/SVG/PDF).
    force_attachment = not sniffed_is_image

    # Thumbnail only for confirmed image files.
    thumbnail_filename = None
    if file_type == 'image' and sniffed_is_image:
        thumbnail_filename = f"thumb_{unique_filename}"
        thumbnail_path = os.path.join(upload_folder, thumbnail_filename)
        _create_thumbnail(file_path, thumbnail_path)

    base_url = str(request.base_url).rstrip('/')

    # Document text extraction. Extractable office/text docs → markitdown →
    # Markdown (clipped to DOC_EXTRACT_MAX_CHARS). Native PDFs are forwarded as
    # a data URL downstream, so they record status 'na' and skip extraction.
    # Images / everything else leave extraction_status NULL.
    extracted_text = None
    extracted_chars = 0
    extraction_status = None
    # ZIP archives expand into one Markdown digest (the archive listing + any
    # extracted text) PLUS each embedded image surfaced as its own sibling
    # attachment. Existing consumers read ``.upload`` and ignore the rest.
    extra_attachments: list[dict] = []
    # The archive's file listing (``[{name, size, kind}]``), surfaced on the
    # zip upload so the frontend chip can show what was read. ``None`` (omitted)
    # for every non-zip upload.
    zip_entries: list[dict] | None = None
    if extension == 'zip':
        try:
            with open(file_path, 'rb') as fh:
                file_bytes = fh.read()
        except OSError as exc:  # noqa: BLE001 - read failure → mark error, keep file
            logger.warning("upload: failed to read zip for extraction: %s", exc)
            file_bytes = None
        if file_bytes is None:
            extraction_status = 'error'
        else:
            result = document_extraction_service.extract_zip(
                file_bytes,
                max_chars=settings.get('DOC_EXTRACT_MAX_CHARS', 200000),
            )
            extraction_status = result.get('status')
            if result.get('markdown'):
                extracted_text = result['markdown']
                extracted_chars = result.get('chars', 0)
            # Cap the archive listing so a pathological zip can't bloat the
            # response; the frontend chip only needs a representative sample.
            zip_entries = (result.get('entries') or [])[:50]
            # Surface up to 10 embedded images as standalone image uploads.
            for img in (result.get('images') or [])[:10]:
                try:
                    img_raw = base64.b64decode(img.get('bytes_b64') or '', validate=False)
                except (ValueError, TypeError):
                    continue
                if not img_raw:
                    continue
                img_ext = _ext_for_image_mime(img.get('mime'))
                img_filename = f"{_uuid.uuid4().hex}.{img_ext}"
                img_path = os.path.join(upload_folder, img_filename)
                try:
                    with open(img_path, 'wb') as ifh:
                        ifh.write(img_raw)
                except OSError as exc:  # noqa: BLE001 - skip this image on write failure
                    logger.warning("upload: failed to write zip image: %s", exc)
                    continue
                img_thumb_filename = f"thumb_{img_filename}"
                img_thumb_path = os.path.join(upload_folder, img_thumb_filename)
                if not _create_thumbnail(img_path, img_thumb_path):
                    img_thumb_filename = None
                img_original = img.get('name') or img_filename
                img_doc = UploadModel.create(
                    user_id=user_id,
                    filename=img_filename,
                    original_name=img_original,
                    mime_type=img.get('mime') or f"image/{img_ext}",
                    size=len(img_raw),
                    type='image',
                    thumbnail_filename=img_thumb_filename,
                    force_attachment=False,
                    extracted_text=None,
                    extracted_chars=0,
                    extraction_status=None,
                )
                img_id = str(img_doc['_id'])
                extra_attachments.append({
                    'id': img_id,
                    'original_name': img_original,
                    'type': 'image',
                    'size': len(img_raw),
                    'url': f"{base_url}/api/uploads/{img_id}",
                    'thumbnail_url': (
                        f"{base_url}/api/uploads/{img_id}/thumbnail"
                        if img_thumb_filename else None
                    ),
                    'extraction_status': None,
                })
    elif document_extraction_service.is_extractable(extension):
        try:
            with open(file_path, 'rb') as fh:
                file_bytes = fh.read()
        except OSError as exc:  # noqa: BLE001 - read failure → mark error, keep file
            logger.warning("upload: failed to read for extraction: %s", exc)
            file_bytes = None
        if file_bytes is None:
            extraction_status = 'error'
        else:
            result = document_extraction_service.extract_text(
                file_bytes,
                filename=original_name,
                mime_type=file.content_type,
                extension=extension,
                max_chars=settings.get('DOC_EXTRACT_MAX_CHARS', 200000),
            )
            extraction_status = result['status']
            if result['markdown']:
                extracted_text = result['markdown']
                extracted_chars = result['chars']
    elif document_extraction_service.is_native_pdf(extension):
        extraction_status = 'na'
    elif extension in _MEDIA_EXTENSIONS:
        # Audio/video have no text to extract; forwarded to A/V-capable models
        # downstream. Mark 'na' (not NULL) so the status is unambiguous.
        extraction_status = 'na'

    upload_doc = UploadModel.create(
        user_id=user_id,
        filename=unique_filename,
        original_name=original_name,
        mime_type=file.content_type,
        size=file_size,
        type=file_type,
        thumbnail_filename=thumbnail_filename,
        force_attachment=force_attachment,
        extracted_text=extracted_text,
        extracted_chars=extracted_chars,
        extraction_status=extraction_status,
    )
    upload_id = str(upload_doc['_id'])

    text_preview = extracted_text[:200] if extracted_text else None

    file_url = f"{base_url}/api/uploads/{upload_id}"
    thumbnail_url = (
        f"{base_url}/api/uploads/{upload_id}/thumbnail" if thumbnail_filename else None
    )

    upload_payload = {
        'id': upload_id,
        'filename': unique_filename,
        'original_name': original_name,
        'type': file_type,
        'size': file_size,
        'url': file_url,
        'thumbnail_url': thumbnail_url,
        'extraction_status': extraction_status,
        'extracted_chars': extracted_chars,
        'text_preview': text_preview,
    }
    # Only zip uploads carry the archive listing; absent for everything else.
    if zip_entries is not None:
        upload_payload['zip_entries'] = zip_entries

    return JSONResponse({
        'upload': upload_payload,
        'extra_attachments': extra_attachments,
    }, status_code=201)


# ===========================================================================
# /api/uploads  (uploads_bp)
# ===========================================================================
@router.post("/file")
def upload_file(
    request: Request,
    file: UploadFile = File(None),
    user: dict = Depends(require_active),
):
    """Upload a file."""
    user_id = str(user['_id'])
    if file is None or file.filename is None:
        return JSONResponse({'error': 'No file provided'}, status_code=400)
    return _handle_upload(file, user_id, request)


@router.post("/image")
def upload_image(
    request: Request,
    file: UploadFile = File(None),
    user: dict = Depends(require_active),
):
    """Upload an image (with validation)."""
    user_id = str(user['_id'])
    if file is None or file.filename is None:
        return JSONResponse({'error': 'No file provided'}, status_code=400)

    if file.filename == '':
        return JSONResponse({'error': 'No file selected'}, status_code=400)

    extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
    if extension not in _IMAGE_EXTENSIONS:
        return JSONResponse({'error': 'File must be an image'}, status_code=400)

    return _handle_upload(file, user_id, request)


@router.get("/video/{filename:path}")
def get_generated_video(filename: str, exp: str | None = None, sig: str | None = None):
    """Serve a workflow-generated mp4 by its on-disk filename.

    Public/unauthenticated by necessity: the workflow UI renders these via a
    plain ``<video src>`` tag, which can't carry a Bearer token. Access control is
    a self-contained HMAC signature (``?exp=<epoch>&sig=<b64url>``) minted in
    ``OpenRouterService`` and verified here (``services/signed_urls.py``).

    Defense in depth — the original capability guards stay: ONLY ``video_*.mp4``
    is servable (chat upload attachments also land in ``UPLOAD_FOLDER`` as
    ``<uuid4>.mp4`` and must NOT be fetchable cross-user here), and any path
    component (``..``, ``/``) is rejected via ``os.path.basename``.

    Enforcement is staged so old persisted (unsigned) URLs survive one release:
      * ``MEDIA_URL_SIGNING_REQUIRED`` truthy  -> unsigned/invalid => 403.
      * default (unset)                        -> unsigned serves (one-time
        deprecation warning), but a PRESENT-but-INVALID signature is ALWAYS 403
        (tamper attempt), independent of the flag.
    Flip the env once all clients re-render signed URLs to make signing mandatory.
    """
    safe_name = os.path.basename(filename)
    if (
        safe_name != filename
        or not safe_name.startswith('video_')
        or not safe_name.lower().endswith('.mp4')
    ):
        return JSONResponse({'error': 'Invalid filename'}, status_code=400)

    from app.services.signed_urls import signing_required, verify_video_url

    has_sig = sig is not None
    if has_sig:
        # A signature was supplied: it must be valid + unexpired, ALWAYS — a
        # tampered/expired link is rejected regardless of the enforcement flag.
        if not verify_video_url(safe_name, exp, sig):
            return JSONResponse({'error': 'Invalid or expired video URL'}, status_code=403)
    elif signing_required():
        # Hard enforcement on: an unsigned URL is no longer acceptable.
        return JSONResponse({'error': 'Signed video URL required'}, status_code=403)
    else:
        # Grace period: serve the legacy unsigned URL but flag it once so we can
        # confirm signed URLs have fully rolled out before flipping the env.
        logger.warning(
            'unsigned video URL served (deprecated; set MEDIA_URL_SIGNING_REQUIRED '
            'to enforce): %s', safe_name
        )

    upload_folder = _get_upload_folder()
    file_path = os.path.join(upload_folder, safe_name)
    if not os.path.isfile(file_path):
        return JSONResponse({'error': 'Video not found'}, status_code=404)

    return FileResponse(file_path, media_type='video/mp4', filename=safe_name)


@router.get("/my")
def get_my_uploads(
    request: Request,
    page: int = 1,
    limit: int = 20,
    user: dict = Depends(require_active),
):
    """Get the user's uploads.

    Registered BEFORE the dynamic ``/{upload_id}`` GET — Starlette matches in
    declaration order, so ``/my`` must precede the catch-all id param or it
    would be swallowed as an upload id.
    """
    user_id = str(user['_id'])

    skip = (page - 1) * limit
    uploads = UploadModel.find_by_user(user_id, skip=skip, limit=limit)
    total = UploadModel.count_by_user(user_id)

    base_url = str(request.base_url).rstrip('/')
    for upload in uploads:
        upload['url'] = f"{base_url}/api/uploads/{upload['_id']}"
        if upload.get('thumbnail_filename'):
            upload['thumbnail_url'] = f"{base_url}/api/uploads/{upload['_id']}/thumbnail"

    return JSONResponse({
        'uploads': serialize_doc(uploads),
        'total': total,
        'page': page,
        'limit': limit,
    }, status_code=200)


@router.get("/{upload_id}")
def get_upload(upload_id: str, user: dict = Depends(current_user)):
    """Serve an uploaded file — JWT, owner-only (404 for non-owner)."""
    current_user_id = str(user['_id'])

    upload = UploadModel.find_by_id(upload_id)
    if upload is None:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    # 404 (not 403) to avoid leaking existence to other users.
    if str(upload['user_id']) != current_user_id:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    safe_name = _safe_serve_name(upload['filename'])
    if safe_name is None:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    upload_folder = _get_upload_folder()
    file_path = os.path.join(upload_folder, safe_name)
    if not os.path.isfile(file_path):
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    # Advertise the human-readable original name (e.g. "فروش.xlsx") in the
    # Content-Disposition so downloads don't land as the opaque UUID disk name.
    # The disk path stays ``safe_name``; only the suggested filename changes.
    # Starlette RFC 5987-encodes non-ASCII, so Persian/Unicode names are fine.
    original = (upload.get('original_name') or '').strip()
    download_name = os.path.basename(original) if original else ''
    download_name = download_name.replace('/', '').replace('\\', '').strip() or safe_name

    as_attachment = bool(upload.get('force_attachment'))
    content_disposition = 'attachment' if as_attachment else 'inline'
    return FileResponse(
        file_path,
        filename=download_name,
        content_disposition_type=content_disposition,
    )


@router.get("/{upload_id}/thumbnail")
def get_thumbnail(upload_id: str, user: dict = Depends(current_user)):
    """Serve a thumbnail for an uploaded image — JWT, owner-only."""
    current_user_id = str(user['_id'])

    upload = UploadModel.find_by_id(upload_id)
    if upload is None:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    # 404 (not 403) to avoid leaking existence to other users.
    if str(upload['user_id']) != current_user_id:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    if not upload.get('thumbnail_filename'):
        return JSONResponse({'error': 'No thumbnail available'}, status_code=404)

    safe_name = _safe_serve_name(upload['thumbnail_filename'])
    if safe_name is None:
        return JSONResponse({'error': 'No thumbnail available'}, status_code=404)

    upload_folder = _get_upload_folder()
    file_path = os.path.join(upload_folder, safe_name)
    if not os.path.isfile(file_path):
        return JSONResponse({'error': 'No thumbnail available'}, status_code=404)

    return FileResponse(file_path, filename=safe_name)


@router.delete("/{upload_id}")
def delete_upload(upload_id: str, user: dict = Depends(require_active)):
    """Delete an uploaded file."""
    user_id = str(user['_id'])

    upload = UploadModel.find_by_id(upload_id)
    if upload is None:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    if str(upload['user_id']) != user_id:
        return JSONResponse({'error': 'Upload not found'}, status_code=404)

    upload_folder = _get_upload_folder()
    try:
        safe_name = _safe_serve_name(upload['filename'])
        if safe_name:
            target = os.path.join(upload_folder, safe_name)
            if os.path.exists(target):
                os.remove(target)
        thumb = upload.get('thumbnail_filename')
        safe_thumb = _safe_serve_name(thumb) if thumb else None
        if safe_thumb:
            thumbnail_path = os.path.join(upload_folder, safe_thumb)
            if os.path.exists(thumbnail_path):
                os.remove(thumbnail_path)
    except Exception as exc:  # noqa: BLE001
        logger.warning("delete_upload: failed to remove files: %s", exc)

    UploadModel.delete(upload_id)
    return JSONResponse({'message': 'Upload deleted'}, status_code=200)




__all__ = ["router", "_get_upload_folder", "_safe_serve_name"]
