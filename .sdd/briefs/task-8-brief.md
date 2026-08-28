# Global Constraints (apply to every task)
- Single user, no signup flow — the one account is provisioned via a CLI script, never a web route.
- Every filesystem path derived from user input MUST go through `resolve_safe_path()` (Task 8) before any read/write/stat call. No exceptions, no "trusted" callers.
- Passwords: Argon2id only (`argon2-cffi`), never stored or logged in plaintext.
- Sessions are opaque random tokens; only their SHA-256 hash is stored in SQLite — a DB read alone must never yield a usable session token.
- All mutating routes (`POST`/`DELETE`) require both a valid session AND a matching CSRF header — no exceptions.
- No CDN references at runtime. All JS/CSS the browser loads comes from `/static/`, vendored into the image at build time.
- Container binds `127.0.0.1`/LAN only. It never terminates public TLS itself — that's the existing Cloudflare Tunnel's job.

---

### Task 8: Safe path resolution

**Files:**
- Create: `app/files/__init__.py`
- Create: `app/files/pathutils.py`
- Test: `tests/test_pathutils.py`

**Interfaces:**
- Produces: `app.files.pathutils.UnsafePathError(Exception)`, `resolve_safe_path(root: Path, relative: str) -> Path`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pathutils.py
import pytest


def test_resolves_normal_path(tmp_path):
    from app.files.pathutils import resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()
    (root / "sub").mkdir()

    result = resolve_safe_path(root, "sub/doc.pdf")
    assert result == (root / "sub" / "doc.pdf").resolve()


def test_rejects_parent_traversal(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "../../etc/passwd")


def test_rejects_absolute_path_escape(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "/etc/passwd")


def test_rejects_symlink_escape(tmp_path):
    from app.files.pathutils import UnsafePathError, resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret")
    (root / "link").symlink_to(outside / "secret.txt")

    with pytest.raises(UnsafePathError):
        resolve_safe_path(root, "link")


def test_empty_relative_path_returns_root(tmp_path):
    from app.files.pathutils import resolve_safe_path

    root = tmp_path / "files"
    root.mkdir()

    assert resolve_safe_path(root, "") == root.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pathutils.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.files'`

- [ ] **Step 3: Write `app/files/pathutils.py`**

```python
# app/files/pathutils.py
import os
from pathlib import Path


class UnsafePathError(Exception):
    pass


def resolve_safe_path(root: Path, relative: str) -> Path:
    root_resolved = root.resolve()
    candidate = (root_resolved / relative.lstrip("/")).resolve()

    try:
        candidate.relative_to(root_resolved)
    except ValueError:
        raise UnsafePathError(f"Path escapes root: {relative}")

    return candidate
```

Note: `Path.resolve()` follows symlinks, so a symlink inside `root` that points outside it resolves to its real (outside) target before the `relative_to` check runs — that's what makes `test_rejects_symlink_escape` pass.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pathutils.py -v`
Expected: PASS (5 tests)

