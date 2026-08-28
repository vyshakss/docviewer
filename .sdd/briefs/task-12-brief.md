# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 12: Docx/doc to PDF conversion with disk cache

**Files:**
- Create: `app/preview/__init__.py`
- Create: `app/preview/convert.py`
- Test: `tests/test_convert.py`

**Interfaces:**
- Produces: `app.preview.convert.ConversionError(Exception)`, `get_preview_pdf(source: Path, cache_dir: Path, timeout: int = 120) -> Path`.
- This task mocks `subprocess.run` in tests — it does not require LibreOffice to be installed on the dev machine to pass.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_convert.py
from pathlib import Path
from unittest.mock import patch


def test_returns_cached_pdf_without_reconverting(tmp_path):
    from app.preview.convert import get_preview_pdf

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    from app.preview.convert import _cache_key
    key = _cache_key(source)
    cached_pdf = cache_dir / f"{key}.pdf"
    cached_pdf.write_bytes(b"%PDF-1.4 cached")

    with patch("app.preview.convert.subprocess.run") as mock_run:
        result = get_preview_pdf(source, cache_dir)
        mock_run.assert_not_called()

    assert result == cached_pdf


def test_converts_when_not_cached(tmp_path):
    from app.preview.convert import get_preview_pdf, _cache_key

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    key = _cache_key(source)
    expected_output = cache_dir / f"{key}.pdf"

    def fake_run(cmd, timeout, capture_output, check):
        # Real LibreOffice names output after the source stem, not our cache
        # key — get_preview_pdf must rename it into place after conversion.
        (cache_dir / f"{source.stem}.pdf").write_bytes(b"%PDF-1.4 converted")

        class Result:
            returncode = 0

        return Result()

    with patch("app.preview.convert.subprocess.run", side_effect=fake_run) as mock_run:
        result = get_preview_pdf(source, cache_dir)
        mock_run.assert_called_once()

    assert result == expected_output
    assert result.read_bytes() == b"%PDF-1.4 converted"


def test_raises_on_conversion_failure(tmp_path):
    from app.preview.convert import ConversionError, get_preview_pdf

    source = tmp_path / "doc.docx"
    source.write_bytes(b"fake docx")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    class Result:
        returncode = 1

    with patch("app.preview.convert.subprocess.run", return_value=Result()):
        try:
            get_preview_pdf(source, cache_dir)
            assert False, "expected ConversionError"
        except ConversionError:
            pass


def test_cache_key_changes_with_mtime(tmp_path):
    from app.preview.convert import _cache_key
    import os

    source = tmp_path / "doc.docx"
    source.write_bytes(b"v1")
    key1 = _cache_key(source)

    os.utime(source, (source.stat().st_atime, source.stat().st_mtime + 10))
    key2 = _cache_key(source)

    assert key1 != key2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_convert.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.preview'`

- [ ] **Step 3: Write `app/preview/convert.py`**

LibreOffice's `--convert-to` names its output after the *source* filename
(`<source_stem>.pdf`), not our cache key — so the function converts into a
temp name and renames to the cache-key filename afterward.

```python
# app/preview/convert.py
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
```

Note the test's `fake_run` above writes to `cache_dir / f"{source.stem}.pdf"`
(not directly to the cache-key path) precisely to exercise this rename step —
that's the real LibreOffice output-naming behavior being simulated.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_convert.py -v`
Expected: PASS (4 tests)

