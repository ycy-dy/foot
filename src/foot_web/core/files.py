"""Atomically expose complete immutable artifacts, including after an interrupted retry."""
import os
import tempfile
from pathlib import Path


def write_once(path, text):
    path = Path(path)
    data = text.encode('utf-8')
    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError('冻结产物已存在且内容不同')
        return
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
