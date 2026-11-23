"""FileService — file system operations (upload, read, delete)."""

import os
from typing import Any, BinaryIO, Dict, Optional

from penclip.logger import debug

_VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg")


class FileService:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._base_dir = self._config.get("base_dir", "data")
        debug(f"FileService initialized (base_dir={self._base_dir})")

    def is_local_video(self, path: str) -> bool:
        """True when ``path`` points at an existing video file on this machine."""
        if not path:
            return False
        lower = path.lower()
        return os.path.isfile(path) and any(lower.endswith(ext) for ext in _VIDEO_EXTENSIONS)

    def resolve_video(self, path: str) -> Optional[str]:
        """Resolve an asset reference to a readable local video path.

        V0.1 records remote URLs without downloading them, so a non-existent
        path returns None instead of raising — callers decide whether to skip.
        """
        if self.is_local_video(path):
            return os.path.abspath(path)
        return None

    def save(self, filename: str, data: bytes) -> str:
        path = os.path.join(self._base_dir, filename)
        os.makedirs(os.path.dirname(path) or self._base_dir, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path

    def read(self, path: str) -> bytes:
        with open(path, "rb") as f:
            return f.read()

    def delete(self, path: str) -> bool:
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def exists(self, path: str) -> bool:
        return os.path.exists(path)
