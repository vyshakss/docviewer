# Task 11 Report: Rename, move, delete

## Summary

Added `POST /api/rename`, `POST /api/move`, and `DELETE /api/files/{path:path}` to the
existing `app/files/routes.py` router (same file/router as `GET /api/files`,
`GET /api/download/{path:path}`, `POST /api/upload`), and appended 13 new tests to
`tests/test_files_routes.py`. Followed the brief's steps in order: wrote the tests first,
verified they failed (routes not implemented), implemented the routes with a security
adjustment to the `new_name` validation, verified all new tests pass, then ran the full
suite.

## Files modified

- `/run/media/vyshak/ssd/docviewer/app/files/routes.py`
  - Added imports: `shutil` (stdlib), `BaseModel` from `pydantic`.
  - Added `RenameBody` (`path: str`, `new_name: str`) and `MoveBody` (`path: str`,
    `dest: str`) pydantic models.
  - Added `POST /rename` (registered as `/api/rename`): validates `new_name` (see Security
    Analysis below), resolves `path` via `resolve_safe_path()`, 404 if source missing, 409
    if target already exists, then `source.rename(target)`.
  - Added `POST /move` (registered as `/api/move`): resolves both `path` and `dest` via
    `resolve_safe_path()`, 404 if source missing, 409 if dest already exists, creates
    intermediate dest directories, then `shutil.move()`.
  - Added `DELETE /files/{path:path}` (registered as `/api/files/{path:path}`): resolves
    `path` via `resolve_safe_path()`, 404 if missing, `shutil.rmtree()` for directories or
    `unlink()` for files.
  - All three routes require `get_current_user` + `require_csrf` (mutating routes).

- `/run/media/vyshak/ssd/docviewer/tests/test_files_routes.py`
  - Appended 13 tests, reusing the existing `_authed_client` helper (not redefined):
    `test_rename_file`, `test_move_file`, `test_delete_file`,
    `test_rename_rejects_traversal_target` (all four from the brief's Step 1),
    plus additional tests written during the security review:
    `test_rename_rejects_absolute_new_name`, `test_rename_rejects_dotdot_new_name`,
    `test_rename_requires_csrf`, `test_move_rejects_traversal_source`,
    `test_move_rejects_traversal_dest`, `test_move_requires_csrf`,
    `test_delete_rejects_traversal`, `test_delete_requires_csrf`,
    `test_delete_directory_recursive`.
  - Existing tests were left untouched.

## Security analysis of `new_name` / `path` / `dest` handling

This was the explicit focus given the Task 10 upload-filename vulnerability (arbitrary
file write via unvalidated `file.filename` used directly to build a filesystem path). I
scrutinized each new user-input field before implementing:

**`path` (rename source, move source) and `path`/`{path:path}` (delete)** — always passed
straight into `resolve_safe_path(settings.files_root, path)`, exactly like the existing
`list_files`/`download_file`/`upload_file` routes. `resolve_safe_path` resolves the
candidate against the root and rejects (`UnsafePathError` → 400) anything that resolves
outside `files_root`. No bypass found — these never touch the filesystem directly.

**`dest` (move)** — also passed straight into `resolve_safe_path()`. Because `dest` is
meant to represent an arbitrary destination *within* the tree (it can and should contain
`/` to place a file in a subdirectory, as `test_move_file` exercises with `sub/a.txt`), it
cannot be constrained to a single path segment the way `new_name` can — sandboxing it via
`resolve_safe_path` (which already permits multi-segment paths as long as they resolve
within root) is the correct control here, and it's the same control already trusted for
`path` on every existing route. `dest.parent.mkdir(parents=True, exist_ok=True)` operates
on `dest.parent`, which is itself guaranteed within `files_root` because `dest` was
resolved within it. Verified with `test_move_rejects_traversal_dest` (encoded `..` segments
→ 400, source file untouched).

**`new_name` (rename) — the field directly analogous to Task 10's vulnerable `filename`.**
The brief's sample code was:

```python
if "/" in body.new_name or body.new_name in ("", ".", ".."):
    raise HTTPException(status_code=400, detail="Invalid new name")
...
target = source.parent / body.new_name
```

I did not implement this literally. Instead of blindly copying it, I checked it against the
exact failure mode from Task 10 (`Path(x).name` vs. raw input mismatch) and against Python's
actual `Path.name` semantics (verified interactively — `Path("..").name == ".."`,
`Path(".").name == ""`, `Path("/a").name == "a"`, `Path("a/b").name == "b"`, etc.), rather
than assuming the brief's simpler slash-check was equivalent by inspection alone. On Linux
(this project's only target platform — no Windows backslash separator to worry about), the
brief's check (`"/" in new_name` catches any embedded separator, including a leading `/`
that would make the value absolute; the explicit `("", ".", "..")` membership check catches
the two dot-segments that don't contain `/`) is in fact **behaviorally equivalent** to Task
10's `Path(x).name != raw_input` reduction-and-compare approach for this input domain — I
did not find a bypass of the brief's version.

However, I still changed the implementation to use the exact Task 10 pattern rather than
the brief's version, for two reasons: (1) it keeps the codebase's file-write validation
uniform — one reviewed, load-bearing pattern (`reduce to Path(x).name, reject on mismatch`)
instead of two independently-written checks that happen to be equivalent but aren't
obviously so at a glance; (2) it's more robust to close semantic gaps I can't fully rule
out (e.g. any future change to what counts as a "single segment" on a different filesystem
or Python version) since it derives the safe value from the platform's own `Path` parser
rather than hand-enumerating disallowed characters/values. The implemented check:

```python
raw_new_name = body.new_name
new_name = Path(raw_new_name).name
if not new_name or new_name in (".", "..") or new_name != raw_new_name:
    raise HTTPException(status_code=400, detail="Invalid new name")
...
target = source.parent / new_name
```

`target = source.parent / new_name` is safe because `new_name` is confirmed to be a single,
non-traversal path segment, and `source.parent` is itself already confirmed within
`files_root` (it's derived from `source`, which came from `resolve_safe_path`). This
mirrors the Task 10 fix's structure (`dest = target_dir / filename` after validating
`filename`) exactly.

**Conclusion: no new arbitrary-file-write vulnerability found in the brief's sample code
for this task** — unlike Task 10, the rename route's `new_name` validation in the brief was
already correct in effect. I nonetheless normalized it to the established, reviewed
`Path(x).name`-comparison pattern rather than keep a second, differently-shaped check doing
the same job, and added regression tests for both the absolute-path and `..`-only exploit
shapes (`test_rename_rejects_absolute_new_name`, `test_rename_rejects_dotdot_new_name`) to
pin this down the same way Task 10's regression tests do for upload.

## Deviations from the brief

1. **`new_name` validation rewritten** (see above) — from the brief's
   `"/" in body.new_name or body.new_name in ("", ".", "..")` to the Task-10-style
   `Path(x).name` reduce-and-compare. Verified equivalent for this input domain; changed for
   consistency with the already-reviewed upload fix and to derive safety from the platform's
   path parser rather than a hand-written character check.
2. **`test_delete_rejects_traversal` uses percent-encoded dot segments
   (`/api/files/%2e%2e/%2e%2e/etc/passwd`) instead of literal `../../etc/passwd`.** The
   brief didn't include this test (it only specified a rename traversal test), but I added
   delete/move traversal tests for symmetry with the existing upload/list traversal tests.
   While writing it, a literal `../../etc/passwd` URL path segment turned out to be
   normalized away by httpx itself before the request left the client (confirmed via
   `httpx.Request(...).url` — it collapses to `https://testserver/etc/passwd`, which just
   404s as an unmatched route and would pass the assertion for the wrong reason, testing the
   HTTP client's own normalization instead of the server's `resolve_safe_path` defense).
   Percent-encoding the dots (`%2e%2e`) preserves the literal `..` bytes through client-side
   normalization so Starlette decodes them into the path param, letting the test actually
   exercise `resolve_safe_path()`. Confirmed this reaches the handler and gets a genuine 400.
3. **Added 9 tests beyond the brief's 4** (`test_rename_rejects_absolute_new_name`,
   `test_rename_rejects_dotdot_new_name`, `test_rename_requires_csrf`,
   `test_move_rejects_traversal_source`, `test_move_rejects_traversal_dest`,
   `test_move_requires_csrf`, `test_delete_rejects_traversal`, `test_delete_requires_csrf`,
   `test_delete_directory_recursive`) — covers CSRF enforcement (required by the global
   constraints: "All mutating routes require both a valid session AND a matching CSRF
   header") and traversal rejection for all three new routes, plus recursive directory
   deletion, none of which the brief's 4-test Step 1 covered on its own.

All other code (route bodies for `move_file` and `delete_file`, and the four brief-specified
tests) matches the brief's sample verbatim.

## Test commands and output

1. Wrote all tests (brief's 4 plus the additional security/CSRF ones), then confirmed they
   fail before implementing the routes:

   ```
   $ pytest tests/test_files_routes.py -v -k "rename or move or delete"
   FAILED test_rename_file - assert 404 == 200
   FAILED test_move_file - assert 404 == 200
   FAILED test_delete_file - assert 404 == 200
   FAILED test_rename_rejects_traversal_target - assert 404 == 400
   FAILED test_rename_rejects_absolute_new_name - assert 404 == 400
   FAILED test_rename_rejects_dotdot_new_name - assert 404 == 400
   FAILED test_rename_requires_csrf - assert 404 == 403
   FAILED test_move_rejects_traversal_source - assert 404 == 400
   FAILED test_move_rejects_traversal_dest - assert 404 == 400
   FAILED test_move_requires_csrf - assert 404 == 403
   FAILED test_delete_rejects_traversal - assert 404 == 400
   FAILED test_delete_requires_csrf - assert 404 == 403
   FAILED test_delete_directory_recursive - assert 404 == 200
   13 failed, 10 deselected in 2.88s
   ```

2. Implemented the three routes in `app/files/routes.py`. Re-ran:

   ```
   $ pytest tests/test_files_routes.py -v
   ... 23 passed, 107 warnings in 4.04s
   ```

   (First pass had one failure — `test_delete_rejects_traversal` with a literal
   `../../etc/passwd` URL got 404 instead of 400, root-caused to httpx's own client-side
   dot-segment normalization per the deviation note above; fixed by percent-encoding the
   dots in the test, then all 23 passed.)

3. Full project suite:

   ```
   $ pytest
   ======================= 49 passed, 153 warnings in 5.96s =======================
   ```

   (153 warnings are all pre-existing: pydantic v2 config deprecation,
   `asyncio.iscoroutinefunction` deprecation, and FastAPI `on_event` deprecation — none
   related to this task, consistent with Task 10's report.)

## Manual verification of route behavior (via tests)

- `test_rename_file`: renames `old.txt` → `new.txt` within the same directory, 200, content
  preserved, old path gone.
- `test_move_file`: moves `a.txt` into `sub/a.txt`, 200, content preserved, old path gone.
- `test_delete_file`: deletes `gone.txt`, 200, path gone.
- `test_delete_directory_recursive`: deletes a non-empty directory (`adir/inner.txt`), 200,
  entire subtree gone (`shutil.rmtree` path).
- `test_rename_rejects_traversal_target` / `_rejects_absolute_new_name` /
  `_rejects_dotdot_new_name`: `new_name` of `../../etc/passwd`, an absolute path outside
  `files_root`, and bare `..` are all rejected with 400 and leave the source file untouched.
- `test_move_rejects_traversal_source` / `_rejects_traversal_dest`: encoded-traversal `path`
  or `dest` rejected with 400 (via `resolve_safe_path`), no filesystem changes.
- `test_delete_rejects_traversal`: percent-encoded traversal path segment rejected with 400.
- `test_rename_requires_csrf` / `test_move_requires_csrf` / `test_delete_requires_csrf`:
  omitting `X-CSRF-Token` returns 403 and the filesystem is left unchanged, confirming
  `require_csrf` is wired on all three new mutating routes per the global constraint.

## Files touched

- `/run/media/vyshak/ssd/docviewer/app/files/routes.py`
- `/run/media/vyshak/ssd/docviewer/tests/test_files_routes.py`
- `/run/media/vyshak/ssd/docviewer/.sdd/reports/task-11-report.md` (this report)

## Fix round 1: root-directory mutation and unhandled filesystem errors

### Findings (from task review)

Task review found two critical and two important issues, all stemming from the same gap:
`resolve_safe_path()` legitimately allows the root itself as a valid resolved result (needed
so `path=""` works for listing the root directory), but none of the three new mutating
routes checked whether the *resolved* path was `files_root` itself before mutating it.

- **Critical #1** — `DELETE /api/files/{path}` with `path` resolving to `files_root` itself
  (empty path, `.`, or a percent-encoded `.`) called `shutil.rmtree(files_root)`, deleting
  the entire file store in one request. Reproduced with `DELETE /api/files/` and
  `DELETE /api/files/%2e` — both returned 200 and wiped everything under `files_root`.
- **Critical #2** — `POST /api/rename` with `path=""` resolved `source` to `files_root`
  itself; `target = source.parent / new_name` then computed a path *outside* `files_root`
  (since `source.parent` is `files_root`'s parent directory), and `source.rename(target)`
  relocated the entire file store outside the sandbox. Reproduced with
  `{"path": "", "new_name": "pwned_dir"}` — returned 200 and moved the whole store to a
  sibling directory.
- **Important #1** — `POST /api/move` with `path=""` (source = `files_root`) threw an
  uncaught `shutil.Error` ("Cannot move a directory into itself") → 500 instead of a clean
  4xx.
- **Important #2** — `POST /api/rename` with a null byte in `new_name` (e.g.
  `"evil\x00name"`) threw an uncaught `ValueError` from `os.rename` → 500. `Path(x).name`
  does not strip or reject embedded null bytes, so the existing "differs from raw input"
  check doesn't catch this — the string is unchanged by `.name`, so validation passes, and
  the failure only surfaces at the actual syscall.

### Fixes applied, in `app/files/routes.py`

1. **Root-directory guard** in all three routes, right after resolving the relevant
   path(s) via `resolve_safe_path()` and before any existence/mutation logic:

   - `rename_file`: `if source == settings.files_root.resolve(): raise HTTPException(400, "Cannot operate on the root directory")`.
   - `move_file`: same check against both `source` and `dest`
     (`if source == files_root_resolved or dest == files_root_resolved: ...`) — the root
     must never be a move source *or* destination.
   - `delete_file`: `if target == settings.files_root.resolve(): raise HTTPException(400, "Cannot operate on the root directory")`.

   This closes both Critical findings directly: renaming, moving, or deleting the resolved
   root path is now rejected with 400 before any filesystem call is made.

2. **Defense-in-depth exception handling** around each route's actual mutation call(s),
   converting any unexpected filesystem-level failure into a clean 400 instead of letting it
   propagate as an unhandled 500:

   - `rename_file`: `source.rename(target)` wrapped in
     `try: ... except (OSError, ValueError, shutil.Error): raise HTTPException(400, "Operation failed")`.
     This directly fixes Important #2 — the null-byte `os.rename` `ValueError` is now caught
     and returned as 400.
   - `move_file`: both `dest.parent.mkdir(...)` and `shutil.move(...)` wrapped the same way.
     This directly fixes Important #1 — the `shutil.Error` on a self-move is now caught and
     returned as 400. (In practice, after fix #1 above, `move_file`'s specific `path=""`
     self-move case is already rejected earlier by the root guard; the try/except remains as
     defense-in-depth against any other `shutil.Error`/`OSError` shape, per the review's
     explicit request.)
   - `delete_file`: the `shutil.rmtree(target)` / `target.unlink()` branch wrapped the same
     way, for the same defense-in-depth reasoning.

### New regression tests, in `tests/test_files_routes.py`

Six tests added, each reproducing one of the four findings (delete has two variants — empty
path and percent-encoded `.` — since both were called out in the reproduction):

- `test_delete_rejects_root_via_empty_path`: `DELETE /api/files/` → 400, `files_root` still
  exists afterward with its prior contents intact.
- `test_delete_rejects_root_via_dot_path`: `DELETE /api/files/%2e` → 400, same assertions.
- `test_rename_rejects_root_as_source`: `POST /api/rename {"path": "", "new_name": "pwned_dir"}`
  → 400; asserts `files_root` still resolves to its original location, still exists, its
  contents are intact, and no sibling `pwned_dir` was created.
- `test_rename_rejects_null_byte_in_new_name`: `POST /api/rename` with
  `new_name: "evil\x00name"` → 400 (not 500), source file untouched.
- `test_move_rejects_root_as_source`: `POST /api/move {"path": "", "dest": "somewhere"}` →
  400 (not 500), `files_root` unchanged.
- `test_move_rejects_root_as_dest`: `POST /api/move {"path": "a.txt", "dest": ""}` → 400,
  source file untouched.

### Verification that the new tests actually catch the reported bugs

Before finalizing, I copied the pre-fix (reviewed-as-vulnerable) version of
`app/files/routes.py` — root guards removed from all three routes, and the mutation calls
un-wrapped from try/except — back into place and ran just the six new tests against it:

```
$ pytest tests/test_files_routes.py -v -k "root_as_source or root_as_dest or via_empty_path or via_dot_path or null_byte"
FAILED test_delete_rejects_root_via_empty_path
FAILED test_delete_rejects_root_via_dot_path
FAILED test_rename_rejects_root_as_source
FAILED test_rename_rejects_null_byte_in_new_name
FAILED test_move_rejects_root_as_source - shutil.Error: ...
FAILED test_move_rejects_root_as_dest - assert 40... (500 instead of 400)
6 failed, 23 deselected in 4.22s
```

All six failed against the vulnerable code — confirming each test exercises the specific
bug it targets. I then restored the fixed version (`diff` confirmed byte-identical to the
fix committed above) before re-running the full suite.

### Test output after the fix

```
$ pytest tests/test_files_routes.py -v
======================= 29 passed, 125 warnings in 8.54s =======================

$ pytest -v
====================== 55 passed, 171 warnings in 11.81s =======================
```

29 = the prior 23 in `test_files_routes.py` + 6 new. 55 = the prior 49 full-suite total + 6
new; no regressions elsewhere.

### Files touched in this fix round

- `/run/media/vyshak/ssd/docviewer/app/files/routes.py` (root-directory guards added to
  `rename_file`, `move_file`, `delete_file`; mutation calls in all three wrapped in
  `try/except (OSError, ValueError, shutil.Error)`)
- `/run/media/vyshak/ssd/docviewer/tests/test_files_routes.py` (six new regression tests
  appended)
- `/run/media/vyshak/ssd/docviewer/.sdd/reports/task-11-report.md` (this section)
