# Task 8 Report: Safe path resolution

## Summary

Created the `app/files` package for the first time and implemented
`resolve_safe_path()` / `UnsafePathError`, the single choke point every
later file operation (list, download, upload, rename, move, delete,
preview) must route through. Followed the brief's TDD steps in order:
wrote the test file first, confirmed it failed with
`ModuleNotFoundError`, wrote the implementation, then discovered and
fixed a real bug in the brief's own sample implementation (it failed
one of the brief's own tests), and finally hardened the function
against a null-byte input that the brief's tests didn't cover.

**This task required deviating from the brief's literal implementation
snippet** — see "Deviations from the brief" below for the full
reasoning. The public interface (`UnsafePathError`, `resolve_safe_path(root, relative) -> Path`)
is unchanged.

## Files created/modified

- **Created** `/run/media/vyshak/ssd/docviewer/tests/test_pathutils.py`
  — copied verbatim from the brief (Step 1). Five tests:
  - `test_resolves_normal_path`
  - `test_rejects_parent_traversal`
  - `test_rejects_absolute_path_escape`
  - `test_rejects_symlink_escape`
  - `test_empty_relative_path_returns_root`
- **Created** `/run/media/vyshak/ssd/docviewer/app/files/__init__.py`
  — empty, matching the convention of `app/auth/__init__.py`.
- **Created** `/run/media/vyshak/ssd/docviewer/app/files/pathutils.py`
  — started from the brief's Step 3 snippet, then modified in two
  places (see Deviations). Final contents:

  ```python
  import os
  from pathlib import Path


  class UnsafePathError(Exception):
      pass


  def resolve_safe_path(root: Path, relative: str) -> Path:
      root_resolved = root.resolve()

      try:
          candidate = (root_resolved / relative).resolve()
      except (ValueError, OSError) as exc:
          raise UnsafePathError(f"Path escapes root: {relative}") from exc

      try:
          candidate.relative_to(root_resolved)
      except ValueError:
          raise UnsafePathError(f"Path escapes root: {relative}")

      return candidate
  ```

No other existing files were modified.

## Test commands and output

### Step 2: Verify test fails before implementation exists

Command:
```
.venv/bin/pytest tests/test_pathutils.py -v
```

Result: **5 failed**, all with the expected error:
```
ModuleNotFoundError: No module named 'app.files'
```

### Step 3/4: First implementation attempt (brief's verbatim snippet) — one test failed

Wrote the brief's Step 3 code exactly as given (including
`relative.lstrip("/")`) and re-ran:
```
.venv/bin/pytest tests/test_pathutils.py -v
```

Result: **4 passed, 1 failed**:
```
tests/test_pathutils.py::test_resolves_normal_path PASSED
tests/test_pathutils.py::test_rejects_parent_traversal PASSED
tests/test_pathutils.py::test_rejects_absolute_path_escape FAILED
tests/test_pathutils.py::test_rejects_symlink_escape PASSED
tests/test_pathutils.py::test_empty_relative_path_returns_root PASSED

FAILED tests/test_pathutils.py::test_rejects_absolute_path_escape
  Failed: DID NOT RAISE <class 'app.files.pathutils.UnsafePathError'>
```

Root cause (traced by hand and confirmed with a standalone script): the
brief's line `candidate = (root_resolved / relative.lstrip("/")).resolve()`
strips the leading `/` from `"/etc/passwd"` before joining, turning it
into the *relative* string `"etc/passwd"`. Joined to root, that resolves
to `root/etc/passwd` — safely inside root, not an escape — so
`relative_to()` succeeds and `UnsafePathError` never fires. I.e. the
`lstrip("/")` line silently converts every "absolute path escape"
attempt into a harmless root-relative path, which is exactly the
behavior `test_rejects_absolute_path_escape` was written to catch. This
is a genuine bug in the brief's sample code, not a test environment
issue — confirmed with:

```python
>>> from pathlib import Path
>>> root_resolved = Path('/tmp/testroot').resolve()
>>> candidate = (root_resolved / '/etc/passwd'.lstrip('/')).resolve()
>>> candidate
PosixPath('/tmp/testroot/etc/passwd')   # inside root — no escape detected
```

### Fix applied and re-verified

Removed the `.lstrip("/")` call, joining `relative` to `root_resolved`
unmodified. Pathlib's `/` operator already discards the left operand
when the right side is an absolute path (`Path("/a") / "/etc/passwd" == Path("/etc/passwd")`),
so an absolute `relative` argument now resolves outside root and is
correctly rejected by the existing `relative_to()` check. Re-ran:

```
.venv/bin/pytest tests/test_pathutils.py -v
```

Result: **5 passed**:
```
tests/test_pathutils.py::test_resolves_normal_path PASSED       [ 20%]
tests/test_pathutils.py::test_rejects_parent_traversal PASSED   [ 40%]
tests/test_pathutils.py::test_rejects_absolute_path_escape PASSED [ 60%]
tests/test_pathutils.py::test_rejects_symlink_escape PASSED     [ 80%]
tests/test_pathutils.py::test_empty_relative_path_returns_root PASSED [100%]

============================== 5 passed in 0.09s ===============================
```

### Full suite regression check

Command:
```
.venv/bin/pytest -q
```

Result: **26 passed** (21 pre-existing tests from Tasks 1-7 plus the 5
new ones), 0 failed. Only pre-existing `DeprecationWarning`s from
Starlette/FastAPI/Pydantic on Python 3.14, unrelated to this change.

## Extra traversal-vector sanity checks

Given how security-critical this function is, I probed it with vectors
beyond the brief's five tests, using a throwaway script against a real
`tmp_path`-style root (`root/`, `root/sub/`, non-existent targets).
Results after the final implementation:

| Vector | Input | Result |
|---|---|---|
| Mixed `..` traversal | `sub/../../etc/passwd` | **Blocked** (`UnsafePathError`) |
| Mixed `..` that stays inside | `sub/../sub/doc.pdf` | Allowed → resolves to `root/sub/doc.pdf` (correct — not an escape) |
| Null byte in filename | `sub/doc.pdf\x00.txt` | **Blocked** (`UnsafePathError`) — see note below |
| Backslash-style traversal | `sub\..\..\etc\passwd` | Allowed → treated as one literal filename component `sub\..\..\etc\passwd` under `root/` (correct for POSIX; see note below) |
| Excessive `../` depth (50x) | `../` × 50 + `etc/passwd` | **Blocked** (`UnsafePathError`) |
| Absolute path with extra traversal | `/../../etc/passwd` | **Blocked** (`UnsafePathError`) |
| Bare `.` | `.` | Allowed → resolves to `root` itself (correct, same as empty string) |
| Bare `..` | `..` | **Blocked** (`UnsafePathError`) |

Notes:

1. **Mixed `..` segments** (`sub/../../etc/passwd`): confirmed the
   brief's claim that `Path.resolve()` collapsing `..` segments before
   the `relative_to()` containment check is sufficient — no special
   handling needed. Verified this empirically rather than assuming it;
   it holds.

2. **Null byte**: this was a genuine gap I found and fixed. Before the
   fix, `Path.resolve()` itself raises a raw `ValueError`
   (`lstat: embedded null character in path`) for a relative string
   containing `\x00`, which is a *different* exception type than
   `UnsafePathError`. Since every later route is expected to catch only
   `UnsafePathError` around calls into this function (per the brief's
   own framing — "EVERY later file operation... will go through the
   function"), an uncaught `ValueError` would leak as an unhandled
   exception (500) instead of a clean, intentional rejection. I wrapped
   the `.resolve()` call in `try/except (ValueError, OSError)` and
   re-raise as `UnsafePathError`, so this now fails closed with the
   correct exception type. Re-verified all 5 brief tests plus this
   vector still pass after the change.

3. **Windows-style backslash**: on this Linux/POSIX deployment (the
   brief's global constraints state the container binds
   `127.0.0.1`/LAN only and runs under Docker — Linux, never Windows),
   a backslash is just a literal character in a filename, not a path
   separator. `sub\..\..\etc\passwd` is therefore treated as a single,
   unusual (and in practice non-existent) filename component under
   `root/`, which is correct and safe — it cannot escape `root`. No
   production code change is warranted here since this codebase never
   runs on Windows; noting it for completeness per the task instructions
   rather than because it's a real gap.

4. **Excessive `../` depth**: confirmed the check scales fine
   regardless of how many `..` segments are chained — `resolve()`
   collapses all of them and the resulting path still fails
   `relative_to()` correctly.

No further production code changes were made beyond the null-byte fix;
the other vectors were already handled correctly by the existing
resolve + `relative_to` containment logic.

## Deviations from the brief

Two deviations from the brief's literal Step 3 code, both necessary and
both re-verified against all 5 of the brief's own tests plus the extra
sanity checks:

1. **Removed `relative.lstrip("/")`.** The brief's verbatim snippet
   fails the brief's own `test_rejects_absolute_path_escape` test (see
   detailed trace above) — stripping the leading slash silently rebases
   an absolute-path escape attempt into a harmless root-relative path,
   defeating the very check the test exists to enforce. Dropping the
   `lstrip` call lets pathlib's native "an absolute right-hand operand
   replaces the left" join behavior do the work: an absolute `relative`
   argument now resolves to itself (outside root) and is caught by the
   existing `relative_to()` check. This is the minimal change that
   makes all 5 of the brief's tests pass together; I did not invent new
   test cases to justify it, I used the brief's own test suite as the
   ground truth for correct behavior over the sample implementation
   text.

2. **Added a `try/except (ValueError, OSError)` around the `.resolve()`
   call**, re-raising as `UnsafePathError`. This is not required by any
   of the brief's 5 tests (none of them pass a null byte), but was
   flagged by the task instructions as worth a sanity check, and turned
   up a real gap: a null byte in the input otherwise leaks a raw
   `ValueError` past this function instead of failing closed with
   `UnsafePathError`. Given this function is meant to be the single
   trusted choke point for all filesystem access, silently changing
   exception type on a malformed/malicious input is a real risk for
   downstream callers that only catch `UnsafePathError`. Kept the fix
   minimal and scoped to exactly this failure mode.

The unused `import os` line from the brief's snippet was left in place
verbatim — there is no linter configured in this repo (no
`pyproject.toml`, `.flake8`, or `ruff` config, and `ruff`/`flake8` are
not in `requirements-dev.txt`), so it has no practical effect and
removing it wasn't necessary to satisfy any requirement.

The public interface names and signature
(`UnsafePathError(Exception)`, `resolve_safe_path(root: Path, relative: str) -> Path`)
match the "Produces" interface contract exactly, so downstream tasks
that import these names can rely on them as documented.
