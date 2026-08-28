# Task 12 Report: Docx/doc to PDF conversion with disk cache

## Summary

Created a new, standalone `app/preview` package (independent of `app/files` and
`app/auth`) implementing `get_preview_pdf(source, cache_dir, timeout=120) -> Path` with a
sha256-mtime-based disk cache, and `tests/test_convert.py` with the brief's 4 tests, all
mocking `subprocess.run` — no LibreOffice install required. Followed the brief's steps in
order: wrote the test file, ran it to confirm the expected `ModuleNotFoundError` failure,
wrote the implementation, then confirmed all 4 tests pass. Implementation and tests match
the brief's code verbatim (no deviations).

## Files created

- `/run/media/vyshak/ssd/docviewer/app/preview/__init__.py` — empty, marks the package
  (same pattern as `app/files/__init__.py`).
- `/run/media/vyshak/ssd/docviewer/app/preview/convert.py` — verbatim from the brief:
  - `ConversionError(Exception)` — raised on non-zero return code or missing output.
  - `_cache_key(source: Path) -> str` — sha256 of `f"{source.resolve()}:{mtime_ns}"`, so the
    cache key changes whenever the source file's content/mtime changes.
  - `get_preview_pdf(source: Path, cache_dir: Path, timeout: int = 120) -> Path` — creates
    `cache_dir` if needed, returns the cached PDF path immediately if
    `cache_dir/{key}.pdf` already exists (no subprocess call), otherwise shells out to
    `soffice --headless --convert-to pdf --outdir <cache_dir> <source>`, then renames
    LibreOffice's actual output (`cache_dir/{source.stem}.pdf`) to the cache-key filename
    via `Path.replace()`. Raises `ConversionError` if the subprocess returns non-zero or the
    expected output file doesn't exist afterward.
- `/run/media/vyshak/ssd/docviewer/tests/test_convert.py` — verbatim from the brief, 4 tests:
  - `test_returns_cached_pdf_without_reconverting` — pre-populates the cache-key path,
    asserts `subprocess.run` is never called and the cached path is returned as-is.
  - `test_converts_when_not_cached` — mocks `subprocess.run` with a `side_effect` that
    writes to `cache_dir/{source.stem}.pdf` (simulating LibreOffice's real naming
    behavior, which differs from the cache key), asserts the function renames it to the
    expected cache-key path and returns that path with the correct content.
  - `test_raises_on_conversion_failure` — mocks a `returncode = 1` result, asserts
    `ConversionError` is raised.
  - `test_cache_key_changes_with_mtime` — asserts `_cache_key()` changes when the source
    file's mtime changes (via `os.utime`), even with identical content.

No other files were modified.

## Test commands and output

1. Wrote `tests/test_convert.py` first, ran it against the not-yet-created module to
   confirm the expected failure:

   ```
   $ pytest tests/test_convert.py -v
   ...
   ModuleNotFoundError: No module named 'app.preview.convert'
   4 failed in 0.30s
   ```

   Matches the brief's expected failure exactly.

2. Created `app/preview/__init__.py` and `app/preview/convert.py`, reran:

   ```
   $ pytest tests/test_convert.py -v
   tests/test_convert.py::test_returns_cached_pdf_without_reconverting PASSED [ 25%]
   tests/test_convert.py::test_converts_when_not_cached PASSED              [ 50%]
   tests/test_convert.py::test_raises_on_conversion_failure PASSED          [ 75%]
   tests/test_convert.py::test_cache_key_changes_with_mtime PASSED          [100%]
   4 passed in 0.07s
   ```

3. Full project suite, to confirm no regressions against the existing auth/files tests:

   ```
   $ pytest -v
   ...
   59 passed, 171 warnings in 14.34s
   ```

   59 = the prior 55 (per Task 11's report) + 4 new. All 171 warnings are pre-existing
   deprecation warnings (pydantic v2 config, `asyncio.iscoroutinefunction`, FastAPI
   `on_event`) unrelated to this task, same as noted in the Task 10/11 reports.

## Deviations from the brief

None. `app/preview/__init__.py`, `app/preview/convert.py`, and `tests/test_convert.py` are
all implemented exactly as specified in the brief's Step 1 and Step 3 code blocks.

## Path-safety trust boundary (as instructed)

This module deliberately does **not** call `resolve_safe_path()` or perform any of its own
path-containment validation on `source` or `cache_dir`. Both parameters are typed `Path`
and used directly:

- `source` is read (`.stat()`, passed as a `soffice` argument) but never written to.
- `cache_dir` is created (`mkdir(parents=True, exist_ok=True)`) and written into (the
  converted/cached PDF), using only a filename this module derives itself
  (`f"{key}.pdf"`, a hex sha256 digest — no user-controlled path segments, no `..`, no
  separators possible in a hexdigest) — so even without a resolve_safe_path check, nothing
  a caller passes as `source`'s *name* can influence where inside `cache_dir` the output
  lands.

Per the task instructions, this is by design and correct, not a gap: `get_preview_pdf` is
an internal module whose callers (Task 13's preview route, per the brief) are responsible
for having already validated `source` via `resolve_safe_path()` against the files root
before calling in, and for supplying a `cache_dir` that is itself a fixed, trusted,
server-controlled location (not derived from user input at all — there's no reason a
preview-cache directory would ever come from a request). Re-validating `source`/`cache_dir`
inside this module would be redundant work duplicating a check the caller already performs
and owns, and this module has no independent way to know what "root" a caller's `source`
should be constrained to (this module is intentionally decoupled from `app.files` /
`app.auth` and their `files_root` concept, per the task's independence requirement) — so
implementing containment checks here would either be a no-op duplicate of the caller's
check or, worse, an incorrect guess at the wrong root. I confirmed there is no filesystem
operation in `convert.py` that constructs a path from any *user-supplied string content*
(as opposed to the `source`/`cache_dir` `Path` objects themselves) — the only
string-to-path construction is the sha256 hexdigest cache-key filename, which is safe by
construction.

## Files touched

- `/run/media/vyshak/ssd/docviewer/app/preview/__init__.py` (new)
- `/run/media/vyshak/ssd/docviewer/app/preview/convert.py` (new)
- `/run/media/vyshak/ssd/docviewer/tests/test_convert.py` (new)
- `/run/media/vyshak/ssd/docviewer/.sdd/reports/task-12-report.md` (this report)
