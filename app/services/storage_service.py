"""Supabase Storage helpers.

Uploaded media is stored in Supabase Storage, never in the Render service
filesystem. The backend only proxies the multipart request long enough to
send it to Supabase and stores the resulting public URL in PostgreSQL.
"""

from __future__ import annotations

import mimetypes
import os
import re
import uuid
from pathlib import PurePosixPath
from typing import BinaryIO, Optional

import httpx

from app.core.config import settings

_SAFE_SEGMENT = re.compile(r"[^A-Za-z0-9._/-]+")


def _require_storage_config() -> None:
    missing = []
    if not settings.SUPABASE_URL:
        missing.append("SUPABASE_URL")
    if not settings.SUPABASE_SERVICE_ROLE_KEY:
        missing.append("SUPABASE_SERVICE_ROLE_KEY")
    if not settings.SUPABASE_STORAGE_BUCKET:
        missing.append("SUPABASE_STORAGE_BUCKET")
    if missing:
        raise RuntimeError(
            "Supabase Storage is not configured. Missing: " + ", ".join(missing)
        )


def _clean_path(path: str) -> str:
    path = _SAFE_SEGMENT.sub("-", str(path).strip().replace("\\", "/"))
    path = "/".join(part for part in path.split("/") if part not in ("", ".", ".."))
    if not path:
        raise ValueError("Storage path cannot be empty")
    return path


def public_storage_url(path: str) -> str:
    _require_storage_config()
    safe_path = _clean_path(path)
    base = settings.SUPABASE_URL.rstrip("/")
    bucket = settings.SUPABASE_STORAGE_BUCKET
    return f"{base}/storage/v1/object/public/{bucket}/{safe_path}"


def storage_path_from_url(url: Optional[str]) -> Optional[str]:
    if not url or not isinstance(url, str):
        return None
    marker = f"/storage/v1/object/public/{settings.SUPABASE_STORAGE_BUCKET}/"
    if marker in url:
        return url.split(marker, 1)[1].split("?", 1)[0].lstrip("/")
    return None


def _headers(content_type: str = "application/octet-stream") -> dict[str, str]:
    _require_storage_config()
    key = settings.SUPABASE_SERVICE_ROLE_KEY
    return {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": content_type or "application/octet-stream",
        "x-upsert": "false",
        "Cache-Control": "31536000",
    }


def _iter_file(file_obj: BinaryIO, chunk_size: int = 1024 * 1024):
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        yield chunk


def _upload_sync(file_obj: BinaryIO, path: str, content_type: str) -> str:
    _require_storage_config()
    endpoint = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{_clean_path(path)}"
    )
    try:
        file_obj.seek(0)
        with httpx.Client(timeout=httpx.Timeout(180.0)) as client:
            response = client.post(
                endpoint,
                headers=_headers(content_type),
                content=_iter_file(file_obj),
            )
        if response.status_code >= 400:
            raise RuntimeError(
                f"Supabase Storage upload failed ({response.status_code}): "
                f"{response.text[:500]}"
            )
        return public_storage_url(path)
    finally:
        try:
            file_obj.seek(0)
        except Exception:
            pass


async def upload_upload_file(upload_file, folder: str) -> str:
    """Upload FastAPI UploadFile into Supabase Storage and return public URL."""
    import anyio

    original = os.path.basename(upload_file.filename or "upload.bin")
    extension = PurePosixPath(original).suffix.lower()
    extension = extension if extension and len(extension) <= 12 else ""
    filename = f"{uuid.uuid4().hex}{extension}"
    path = f"{folder.strip('/')}/{filename}"
    content_type = upload_file.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"
    return await anyio.to_thread.run_sync(_upload_sync, upload_file.file, path, content_type)


def _delete_sync(path: str) -> None:
    endpoint = (
        f"{settings.SUPABASE_URL.rstrip('/')}/storage/v1/object/"
        f"{settings.SUPABASE_STORAGE_BUCKET}/{_clean_path(path)}"
    )
    with httpx.Client(timeout=httpx.Timeout(60.0)) as client:
        response = client.delete(endpoint, headers=_headers())
    if response.status_code in (404, 410):
        return
    if response.status_code >= 400:
        raise RuntimeError(
            f"Supabase Storage delete failed ({response.status_code}): {response.text[:500]}"
        )


async def delete_storage_url(url: Optional[str]) -> None:
    path = storage_path_from_url(url)
    if not path:
        return
    import anyio
    await anyio.to_thread.run_sync(_delete_sync, path)
