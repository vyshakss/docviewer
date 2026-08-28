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
