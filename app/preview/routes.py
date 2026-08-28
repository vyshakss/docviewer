# app/preview/routes.py
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path
from app.preview.convert import ConversionError, get_preview_pdf

router = APIRouter()

_DOC_EXTENSIONS = {".docx", ".doc"}


@router.get("/view/{path:path}")
def view_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    suffix = target.suffix.lower()

    if suffix == ".pdf":
        return FileResponse(target, media_type="application/pdf")

    if suffix in _DOC_EXTENSIONS:
        try:
            pdf_path = get_preview_pdf(target, settings.cache_dir)
        except ConversionError:
            raise HTTPException(status_code=502, detail="Conversion failed")
        return FileResponse(pdf_path, media_type="application/pdf")

    raise HTTPException(status_code=415, detail="Unsupported preview type")
