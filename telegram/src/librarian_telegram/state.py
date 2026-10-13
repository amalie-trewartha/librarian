"""The persisted getUpdates offset."""

from __future__ import annotations

from pathlib import Path


class Offset:
    def __init__(self, path: Path):
        self._path = path
        self.value = 0
        if path.is_file():
            try:
                self.value = int(path.read_text().strip())
            except ValueError:
                pass

    def advance(self, value: int) -> None:
        if value > self.value:
            self.value = value
            self._path.write_text(str(value))
