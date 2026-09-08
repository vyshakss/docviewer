# app/files/routes.py
import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.dependencies import get_current_user, require_csrf
from app.config import get_settings
from app.files.pathutils import UnsafePathError, resolve_safe_path

router = APIRouter(prefix="/api")


class RenameBody(BaseModel):
    path: str
    new_name: str


class MoveBody(BaseModel):
    path: str
    dest: str


class MkdirBody(BaseModel):
    path: str
    name: str


@router.get("/files")
def list_files(path: str = "", user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    try:
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=404, detail="Directory not found")

        entries = []
        for child in target.iterdir():
            stat = child.stat()
            entries.append(
                {
                    "name": child.name,
                    "is_dir": child.is_dir(),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                }
            )
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid path")

    return {"entries": entries}


@router.get("/download/{path:path}")
def download_file(path: str, user=Depends(get_current_user)):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    try:
        if not target.exists() or not target.is_file():
            raise HTTPException(status_code=404, detail="File not found")
    except OSError:
        raise HTTPException(status_code=400, detail="Invalid path")

    return FileResponse(target, filename=target.name)


@router.post("/upload")
async def upload_file(
    file: UploadFile,
    path: str = Query(""),
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()
    try:
        target_dir = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    raw_filename = file.filename or ""
    filename = Path(raw_filename).name
    if not filename or filename in (".", "..") or filename != raw_filename:
        raise HTTPException(status_code=400, detail="Invalid filename")

    dest = target_dir / filename
    tmp_dest = target_dir / f".{filename}.part"

    total = 0
    try:
        with open(tmp_dest, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    out.close()
                    tmp_dest.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File too large")
                out.write(chunk)

        os.replace(tmp_dest, dest)
    except HTTPException:
        raise
    except (OSError, ValueError):
        try:
            tmp_dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise HTTPException(status_code=400, detail="Invalid filename or upload failed")

    return {"ok": True, "name": filename, "size": total}


@router.post("/mkdir")
def mkdir(
    body: MkdirBody,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()

    # Same sanitization as rename/upload: `name` becomes a path segment via
    # `parent / name` below, so it must reduce to its own basename with
    # nothing stripped (catches separators, absolute paths, "."/"..").
    raw_name = body.name
    name = Path(raw_name).name
    if not name or name in (".", "..") or name != raw_name:
        raise HTTPException(status_code=400, detail="Invalid folder name")

    try:
        parent = resolve_safe_path(settings.files_root, body.path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not parent.exists() or not parent.is_dir():
        raise HTTPException(status_code=404, detail="Directory not found")

    target = parent / name
    if target.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    try:
        target.mkdir()
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Operation failed")
    return {"ok": True, "name": name}


@router.post("/rename")
def rename_file(
    body: RenameBody,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()

    # `new_name` is user input that becomes a filesystem path segment via
    # `source.parent / new_name` below — the same failure mode as the Task 10
    # upload filename vulnerability. Apply the identical fix: reduce to
    # Path(new_name).name and reject if that differs from the raw input
    # (catches path separators, absolute paths, and "."/"..").
    raw_new_name = body.new_name
    new_name = Path(raw_new_name).name
    if not new_name or new_name in (".", "..") or new_name != raw_new_name:
        raise HTTPException(status_code=400, detail="Invalid new name")

    try:
        source = resolve_safe_path(settings.files_root, body.path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # resolve_safe_path legitimately allows the root itself as a valid result
    # (path="" must resolve to files_root so listing the root works), but
    # files_root itself must never be a rename source: source.parent would
    # then be files_root's *parent* directory, so `source.parent / new_name`
    # would land outside the sandbox entirely, and renaming files_root would
    # relocate the whole file store.
    if source == settings.files_root.resolve():
        raise HTTPException(status_code=400, detail="Cannot operate on the root directory")

    # new_name is confirmed to be a single, non-traversal path segment above,
    # so source.parent / new_name necessarily stays within source's own
    # directory (which is itself already confirmed to be within files_root).
    target = source.parent / new_name

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if target.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    try:
        source.rename(target)
    except (OSError, ValueError, shutil.Error):
        raise HTTPException(status_code=400, detail="Operation failed")
    return {"ok": True}


@router.post("/move")
def move_file(
    body: MoveBody,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()
    try:
        source = resolve_safe_path(settings.files_root, body.path)
        dest = resolve_safe_path(settings.files_root, body.dest)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    files_root_resolved = settings.files_root.resolve()
    # See rename_file: resolve_safe_path legitimately lets path="" resolve to
    # files_root itself, but files_root must never be movable/replaceable —
    # moving it (as source or dest) would relocate or clobber the whole file
    # store, and `shutil.move` raises an uncaught shutil.Error when the
    # source and dest happen to coincide with/inside one another.
    if source == files_root_resolved or dest == files_root_resolved:
        raise HTTPException(status_code=400, detail="Cannot operate on the root directory")

    if not source.exists():
        raise HTTPException(status_code=404, detail="Not found")
    if dest.exists():
        raise HTTPException(status_code=409, detail="Target already exists")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(dest))
    except (OSError, ValueError, shutil.Error):
        raise HTTPException(status_code=400, detail="Operation failed")
    return {"ok": True}


@router.delete("/files/{path:path}")
def delete_file(
    path: str,
    user=Depends(get_current_user),
    _csrf=Depends(require_csrf),
):
    settings = get_settings()
    try:
        target = resolve_safe_path(settings.files_root, path)
    except UnsafePathError:
        raise HTTPException(status_code=400, detail="Invalid path")

    # See rename_file: resolve_safe_path legitimately lets an empty/"."/root
    # path resolve to files_root itself. Without this guard, deleting it
    # would shutil.rmtree() the entire file store in one request.
    if target == settings.files_root.resolve():
        raise HTTPException(status_code=400, detail="Cannot operate on the root directory")

    if not target.exists():
        raise HTTPException(status_code=404, detail="Not found")

    try:
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    except (OSError, ValueError, shutil.Error):
        raise HTTPException(status_code=400, detail="Operation failed")
    return {"ok": True}
