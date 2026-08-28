from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request

from app.auth.dependencies import get_current_user
from app.auth.routes import router as auth_router
from app.config import get_settings
from app.files.routes import router as files_router
from app.preview.routes import router as preview_router

app = FastAPI(title="docviewer", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(auth_router)
app.include_router(files_router)
app.include_router(preview_router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def login_page():
    return FileResponse("app/static/login.html")


@app.get("/app")
def app_page(user=Depends(get_current_user)):
    return FileResponse("app/static/index.html")


@app.on_event("startup")
def _startup() -> None:
    from app.db import init_db

    init_db(get_settings().db_path)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    if request.method == "POST":
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                content_length_bytes = int(content_length)
            except ValueError:
                content_length_bytes = None
            if content_length_bytes is not None and content_length_bytes > get_settings().max_upload_bytes:
                return JSONResponse({"detail": "Request too large"}, status_code=413)

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/healthz")
def healthz() -> JSONResponse:
    return JSONResponse({"status": "ok"})
