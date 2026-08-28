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
