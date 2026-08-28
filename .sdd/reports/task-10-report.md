# Task 10 Report: File upload

## Summary

Added `POST /api/upload` to the existing `app/files/routes.py` router (same file/router as
`GET /api/files` and `GET /api/download/{path:path}`), and appended four new tests to
`tests/test_files_routes.py`. Followed the brief's steps in order: wrote the tests first,
verified they failed with 404 (route not implemented), implemented the route, verified all
4 pass, then ran the full suite.

## Files modified

- `/run/media/vyshak/ssd/docviewer/app/files/routes.py`
  - Added imports: `os` (stdlib), `Query` and `UploadFile` from `fastapi`, `require_csrf` from
    `app.auth.dependencies`.
  - Added `POST /upload` route (full route registered as `/api/upload` via the router's
    `/api` prefix): validates the target directory with `resolve_safe_path()`, requires
    `get_current_user` + `require_csrf`, streams the upload to a `.{filename}.part` temp file
    in 1 MiB chunks, aborts with `413` and deletes the partial file if `max_upload_bytes` is
    exceeded, then atomically `os.replace()`s the temp file onto the final destination.
- `/run/media/vyshak/ssd/docviewer/tests/test_files_routes.py`
  - Appended `test_upload_file`, `test_upload_requires_csrf`, `test_upload_rejects_traversal`,
    `test_upload_rejects_oversize`, reusing the existing `_authed_client` helper (not
    redefined). Existing tests (`test_list_root_directory`, `test_list_requires_auth`,
    `test_list_rejects_traversal`, `test_download_file`) were left untouched.

## Implementation notes

Implementation matches the brief's Step 3 code verbatim, with route logic unchanged. No
deviation in `app/files/routes.py`.

## Test commands and output

1. Wrote the 4 tests from the brief, then confirmed they fail before implementing the route:

   ```
   $ pytest tests/test_files_routes.py -v -k upload
   FAILED tests/test_files_routes.py::test_upload_file - assert 404 == 200
   FAILED tests/test_files_routes.py::test_upload_requires_csrf - assert 404 == 403
   FAILED tests/test_files_routes.py::test_upload_rejects_traversal - assert 404 == 400
   FAILED tests/test_files_routes.py::test_upload_rejects_oversize - assert 404 == 413
   4 failed, 4 deselected
   ```

2. After implementing the route:

   ```
   $ pytest tests/test_files_routes.py -v -k upload
   4 passed, 4 deselected in 1.15s
   ```

3. Full suite:

   ```
   $ pytest
   34 passed, 100 warnings in ~3.5s
   ```

   (100 warnings are all pre-existing: pydantic v2 config deprecation, `asyncio.iscoroutinefunction`
   deprecation, and FastAPI `on_event` deprecation — none related to this task.)

## Flakiness check (`max_upload_bytes` mutation on the cached `Settings` singleton)

The brief's `test_upload_rejects_oversize` mutates `get_settings().max_upload_bytes` directly
on the `lru_cache`d `Settings` instance, with no reset. I checked whether this leaks into
other tests depending on run order:

- **Mechanism**: every test that touches `get_settings()` in this suite (`_authed_client`
  itself, plus `test_list_requires_auth`, `tests/test_config.py`, `tests/test_auth_routes.py`)
  calls `get_settings.cache_clear()` as its first action before reading settings. That clears
  the cache and forces a brand-new `Settings()` object (re-read from env) on the next call, so
  a prior test's in-place mutation of the old cached instance is discarded before any
  subsequent test can observe it.
- **Empirical checks performed**:
  - Ran the full suite (`pytest`) twice in a row: 34 passed both times.
  - Ran `test_upload_rejects_oversize` and `test_upload_file` explicitly in that order (oversize
    mutates the setting first, then the "normal" upload test runs immediately after): both
    passed, confirming `max_upload_bytes` was back to the real default when the second test's
    `_authed_client` ran.
  - Ran the brief's exact code (without any reset) through the reversed-order pair above, plus
    the full suite twice: no failures in any configuration.
  - Ran `test_files_routes.py` in isolation vs. as part of the full suite: both pass (8/8 and
    34/34 respectively).
- **Conclusion**: with the current test suite, this is **not actually flaky** — every consumer
  of `get_settings()` clears the cache before reading it, so the mutation never survives to
  affect another test.

**Decision**: I kept a small defensive fix anyway — wrapped the mutation/assertion in
`try/finally` so `max_upload_bytes` is restored to its original value even if the assertion
raises, and even if a future test is added that reads `get_settings()` without first calling
`cache_clear()`. This is a one-line change with no behavioral difference for the currently
passing suite (verified by testing the brief's exact non-defensive version too — see above),
so it's a low-risk hardening rather than a fix for an observed bug. Noting this as the one
deviation from the brief's literal test code.

## Deviations from the brief

- `test_upload_rejects_oversize`: wrapped the `max_upload_bytes` mutation and the
  request/assertion in `try/finally`, restoring the original value in the `finally` block.
  Reasoning: defensive hardening against future test-order dependencies, not a fix for
  observed flakiness (none was found — see above). All other code (route implementation and
  the other three tests) matches the brief verbatim.

## Manual verification of route behavior (via tests)

- `test_upload_file`: POST with a valid CSRF token uploads `new.txt`, returns 200, and the
  file is written to `settings.files_root / "new.txt"` with the correct content.
- `test_upload_requires_csrf`: POST without `X-CSRF-Token` header returns 403.
- `test_upload_rejects_traversal`: POST with `path=../../etc` returns 400 (rejected by
  `resolve_safe_path`).
- `test_upload_rejects_oversize`: with `max_upload_bytes` patched to 10 bytes, a 100-byte
  upload returns 413 and the partial `.part` file is cleaned up (implicit — route unlinks it
  on the size-exceeded path).

## Fix round 1: arbitrary file write via attacker-controlled `file.filename`

### Finding (from task review)

`upload_file()` built `dest = target_dir / file.filename` using the raw multipart-supplied
filename, which is entirely attacker-controlled and independent of the `path` query parameter
(the only thing `resolve_safe_path()` sandboxes). Because pathlib's `/` operator discards the
left operand when the right operand is an absolute path
(`Path("/foo/bar") / "/etc/passwd" == Path("/etc/passwd")`), an upload with a crafted
`filename` such as `/tmp/some_target_file` could cause `os.replace()` to write the uploaded
content to an arbitrary filesystem location the app process can write to, completely bypassing
`files_root`. This was present in the brief's sample code and was carried over verbatim into
the original implementation.

### Fix applied, in `app/files/routes.py`

1. Added `from pathlib import Path` (stdlib) to the imports.
2. In `upload_file()`, after resolving/validating `target_dir` and before building `dest`/
   `tmp_dest`, added filename validation:

   ```python
   raw_filename = file.filename or ""
   filename = Path(raw_filename).name
   if not filename or filename in (".", "..") or filename != raw_filename:
       raise HTTPException(status_code=400, detail="Invalid filename")
   ```

   - `Path(raw_filename).name` strips any directory components (including a leading `/`),
     giving just the final path segment.
   - The upload is rejected outright (400 "Invalid filename") if: the reduced name is empty,
     is `.` or `..`, or if the reduced name differs from the original supplied filename (which
     means the original contained a path separator, `..`, or a leading `/` — i.e., it wasn't
     already a bare single-segment filename). This satisfies the reviewer's requirement to
     reject rather than silently reinterpret a crafted filename down to its basename.
   - An empty `file.filename` (`None` from FastAPI/Starlette is coerced to `""` first) is
     caught by the same check, turning what was previously an unhandled 500 (from trying to
     open a malformed temp path) into a clean 400.
3. `dest` and `tmp_dest` are now built from the validated `filename`, not `file.filename`:

   ```python
   dest = target_dir / filename
   tmp_dest = target_dir / f".{filename}.part"
   ```

4. The response body now echoes the validated `filename` (`"name": filename`) instead of the
   raw, potentially-path-bearing `file.filename`.

### New regression tests, in `tests/test_files_routes.py`

Added two tests (covering both the absolute-path exploit described by the reviewer and a
relative `../` traversal variant), each asserting a 400 response and that no file was written
outside `settings.files_root`:

- `test_upload_rejects_absolute_filename_path_traversal`: uploads with
  `files={"file": (str(tmp_path / "evil_target.txt"), b"pwned", "text/plain")}` (an absolute
  path sibling to `files_root`, reproducing the reviewer's `/tmp/some_target_file` exploit
  shape) and asserts `resp.status_code == 400`, that the crafted absolute target still doesn't
  exist afterward, and that `files_root` is empty (nothing was written anywhere).
- `test_upload_rejects_relative_filename_path_traversal`: uploads with
  `files={"file": ("../evil.txt", b"pwned", "text/plain")}` and asserts the same — 400, the
  `../`-escaped target doesn't exist, and `files_root` is empty.

### Verification that the tests actually catch the vulnerability

Before finalizing, I temporarily reverted `app/files/routes.py`'s upload route to the original
vulnerable form (`dest = target_dir / file.filename`, `tmp_dest = target_dir /
f".{file.filename}.part"`, unvalidated) and re-ran just the two new tests against it:

```
$ pytest tests/test_files_routes.py -v -k "path_traversal"
FAILED tests/test_files_routes.py::test_upload_rejects_absolute_filename_path_traversal
FAILED tests/test_files_routes.py::test_upload_rejects_relative_filename_path_traversal
FileNotFoundError: [Errno 2] No such file or directory: '.../files/tmp/.../evil_target.txt.part'
```

Both failed against the vulnerable code (surfacing as an unhandled `FileNotFoundError`/500
rather than the previous behavior's success path, because the crafted absolute filename also
corrupts the `.part` temp-file path's intermediate directories in the vulnerable version) —
confirming the tests exercise the bug. I then restored the fixed version (`diff` confirmed
byte-identical to the fix committed above) before re-running the full suite.

### Test output after the fix

```
$ pytest tests/test_files_routes.py -v
tests/test_files_routes.py::test_list_root_directory PASSED
tests/test_files_routes.py::test_list_requires_auth PASSED
tests/test_files_routes.py::test_list_rejects_traversal PASSED
tests/test_files_routes.py::test_download_file PASSED
tests/test_files_routes.py::test_upload_file PASSED
tests/test_files_routes.py::test_upload_requires_csrf PASSED
tests/test_files_routes.py::test_upload_rejects_traversal PASSED
tests/test_files_routes.py::test_upload_rejects_absolute_filename_path_traversal PASSED
tests/test_files_routes.py::test_upload_rejects_relative_filename_path_traversal PASSED
tests/test_files_routes.py::test_upload_rejects_oversize PASSED
======================= 10 passed, 60 warnings in 1.94s ========================

$ pytest -v
... (all tests)
======================= 36 passed, 106 warnings in 3.73s =======================
```

### Files touched in this fix round

- `/run/media/vyshak/ssd/docviewer/app/files/routes.py` (filename validation added to
  `upload_file()`)
- `/run/media/vyshak/ssd/docviewer/tests/test_files_routes.py` (two new regression tests
  appended)
- `/run/media/vyshak/ssd/docviewer/.sdd/reports/task-10-report.md` (this section)
