#!/usr/bin/env python3
"""
Atomic file writes — prevents data corruption from mid-write crashes.
"""

import json
import os
import tempfile


def atomic_json_write(filepath: str, data: dict, indent: int = 2):
    """Write JSON data atomically (write to temp file, then rename).

    This ensures the target file is never left in a partially-written state.
    """
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as tmp_file:
            json.dump(data, tmp_file, indent=indent)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, filepath)
    except Exception:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_text_write(filepath: str, content: str):
    """Write text content atomically."""
    dirpath = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(dirpath, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(dir=dirpath, suffix='.tmp')
    try:
        with os.fdopen(fd, 'w') as tmp_file:
            tmp_file.write(content)
            tmp_file.flush()
            os.fsync(tmp_file.fileno())
        os.replace(tmp_path, filepath)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
