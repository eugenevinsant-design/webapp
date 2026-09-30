# app/api/routes/upload.py
"""
Эндпоинты загрузки файлов сигналов (.csv, .txt) через UI.
WFDB (.hea/.mat) остаются в data/signals/, загружаются через FS.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import List

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.core.csv_loader import (
    ALLOWED_EXTENSIONS,
    MAX_FILE_SIZE_BYTES,
    MAX_FILE_SIZE_MB,
    CSVParsingError,
    CSVFormatError,
    CSVTooLargeError,
    csv_loader,
)
from app.core.loader_registry import loader_registry

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOADS_DIR = Path("./data/uploads")
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_filename(name: str) -> str:
    base = Path(name).name
    safe = SAFE_NAME_RE.sub("_", base).strip("._") or "upload"
    return safe[:128]


@router.post("")
async def upload_signal(
    file: UploadFile = File(...),
    fs: float | None = Form(None),
    name: str | None = Form(None),
):
    """Загрузить CSV/TXT сигнал."""
    original_name = file.filename or "upload"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Неподдерживаемое расширение '{ext}'. "
                   f"Допустимо: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )

    upload_id = uuid.uuid4().hex[:12]
    safe_name = _safe_filename(original_name)
    final_name = f"{upload_id}_{safe_name}"
    dest = UPLOADS_DIR / final_name

    total = 0
    try:
        with dest.open("wb") as f_out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_FILE_SIZE_BYTES:
                    f_out.close()
                    dest.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"Файл превышает лимит {MAX_FILE_SIZE_MB} МБ",
                    )
                f_out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        dest.unlink(missing_ok=True)
        logger.exception("Ошибка сохранения файла")
        raise HTTPException(status_code=500, detail=f"Ошибка сохранения: {e}")
    finally:
        await file.close()

    try:
        sig = csv_loader.load(dest, fs=fs, name=name)
    except CSVTooLargeError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=413, detail=str(e))
    except CSVFormatError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(e))
    except CSVParsingError as e:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Ошибка парсинга: {e}")

    meta = sig.to_dict(signal_id=0)
    meta["upload_id"] = upload_id
    meta["size_mb"] = round(total / 1024 / 1024, 3)

    logger.info(
        f"📥 Загружен {final_name}: {meta['n_sig']} кан., "
        f"{meta['sig_len']} точек, fs={meta['fs']} Гц, "
        f"{meta['size_mb']} МБ"
    )

    return {"status": "ok", "message": "Файл загружен", "signal": meta}


@router.get("/list")
async def list_uploads() -> List[dict]:
    """Список загруженных CSV/TXT файлов в data/uploads/."""
    items = []
    for path in sorted(UPLOADS_DIR.glob("*")):
        if path.name.startswith(".") or path.suffix.lower() not in ALLOWED_EXTENSIONS:
            continue
        try:
            sig = csv_loader.load(path, fs=None, name=None)
            meta = sig.to_dict(signal_id=0)
            meta["size_mb"] = round(path.stat().st_size / 1024 / 1024, 3)
            items.append(meta)
        except Exception as e:
            logger.warning(f"⚠️ Не удалось прочитать {path.name}: {e}")
    return items


@router.delete("/{upload_id}")
async def delete_upload(upload_id: str):
    """Удалить загруженный файл по upload_id."""
    for path in UPLOADS_DIR.glob(f"{upload_id}_*"):
        path.unlink(missing_ok=True)
        logger.info(f"🗑️ Удалён {path.name}")
        return {"status": "ok", "deleted": path.name}
    raise HTTPException(status_code=404, detail="Файл не найден")


@router.get("/supported-formats")
async def supported_formats():
    """Список поддерживаемых форматов (для UI)."""
    return {
        "extensions": loader_registry.supported_extensions(),
        "loaders": loader_registry.list_loaders(),
        "max_size_mb": MAX_FILE_SIZE_MB,
    }
