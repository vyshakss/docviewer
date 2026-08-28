import hashlib
import subprocess
from pathlib import Path


class ConversionError(Exception):
    pass


def _cache_key(source: Path) -> str:
    mtime_ns = source.stat().st_mtime_ns
    raw = f"{source.resolve()}:{mtime_ns}"
    return hashlib.sha256(raw.encode()).hexdigest()


def get_preview_pdf(source: Path, cache_dir: Path, timeout: int = 120) -> Path:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(source)
    cached = cache_dir / f"{key}.pdf"

    if cached.exists():
        return cached

    result = subprocess.run(
        [
            "soffice",
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(cache_dir),
            str(source),
        ],
        timeout=timeout,
        capture_output=True,
        check=False,
    )

    produced = cache_dir / f"{source.stem}.pdf"

    if result.returncode != 0 or not produced.exists():
        raise ConversionError(f"Failed to convert {source} to PDF")

    if produced != cached:
        produced.replace(cached)

    return cached
