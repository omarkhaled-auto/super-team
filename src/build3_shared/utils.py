"""Shared utility functions for Build 3."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def atomic_write_json(path: Path | str, data: Any) -> None:
    """Write JSON data atomically by writing to a temp file then renaming.

    Args:
        path: Target file path.
        data: JSON-serialisable data to write.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(str(tmp_path), str(path))
    except BaseException:
        # Clean up temp file on any failure
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def load_json(path: Path | str) -> dict | None:
    """Load JSON data from a file.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data, or None if the file is missing or invalid.
    """
    path = Path(path)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def ensure_dir(path: Path | str) -> Path:
    """Ensure a directory exists, creating parent directories as needed.

    Args:
        path: Directory path to create.

    Returns:
        The Path object for the directory.
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path
