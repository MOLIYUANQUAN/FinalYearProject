"""他发来的截图和照片：存在 STATE_DIR/uploads，对话里只记 /api/uploads/<编号>；问模型的那一刻才把图读出来。

只收常见图片格式，按文件头判断，不信浏览器报的类型。
"""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.config import STATE_DIR

UPLOADS_DIR = STATE_DIR / "uploads"
PREFIX = "/api/uploads/"
MAX_BYTES = 10 * 1024 * 1024
MAX_PER_MESSAGE = 5
TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}
_ID = re.compile(r"^[0-9a-f]{32}$")

router = APIRouter(tags=["uploads"])


def _sniff(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


def save(data: bytes) -> dict[str, str]:
    ext = _sniff(data)
    if ext is None:
        raise ValueError("只能发图片（PNG、JPG、GIF、WebP）。")
    if len(data) > MAX_BYTES:
        raise ValueError("图片太大了，最多 10MB。")
    upload_id = uuid.uuid4().hex
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOADS_DIR / f"{upload_id}{ext}").write_bytes(data)
    return {"id": upload_id, "url": PREFIX + upload_id}


def find(upload_id: str) -> Path | None:
    if not _ID.match(upload_id or ""):
        return None
    return next((p for p in (UPLOADS_DIR / f"{upload_id}{ext}" for ext in TYPES) if p.is_file()), None)


def data_url(ref: str) -> str | None:
    """对话里记的 /api/uploads/<编号> → 给模型的 data URL；文件不在了就是 None。"""
    path = find(ref[len(PREFIX):]) if ref.startswith(PREFIX) else None
    if path is None:
        return None
    return f"data:{TYPES[path.suffix]};base64,{base64.b64encode(path.read_bytes()).decode()}"


@router.post("/api/uploads")
async def upload(file: UploadFile = File(...)) -> dict[str, str]:
    data = await file.read(MAX_BYTES + 1)
    try:
        return save(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/api/uploads/{upload_id}")
def get_upload(upload_id: str) -> FileResponse:
    path = find(upload_id)
    if path is None:
        raise HTTPException(status_code=404, detail="这张图不在了。")
    return FileResponse(path, media_type=TYPES[path.suffix], headers={"Cache-Control": "private, max-age=31536000, immutable"})
