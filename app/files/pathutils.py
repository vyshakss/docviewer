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
