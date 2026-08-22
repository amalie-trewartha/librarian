"""Read the identity's file-backed memories for the dashboard.

The ``mem`` CLI writes a deliberately small YAML-frontmatter shape.  Keep
the viewer parser equally small: it understands top-level scalar fields and
falls back to filename metadata for legacy files.  A malformed memory should
never make the whole Memories page unavailable.
"""

import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any


_DATED_NAME_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})"
    r"(?:_(?P<id>[0-9a-f]{8}))?_(?P<slug>.+)$"
)


def _frontmatter(text: str) -> dict[str, str]:
    """Return top-level scalar fields from a leading frontmatter block."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    try:
        end = next(
            i
            for i, line in enumerate(lines[1:], start=1)
            if line.strip() == "---"
        )
    except StopIteration:
        return {}

    fields: dict[str, str] = {}
    for line in lines[1:end]:
        # Ignore lists, nested mappings, comments, and malformed lines.  The
        # fields consumed below are all scalars in files produced by bin/mem.
        if line[:1].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not key or not value:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        fields[key] = value
    return fields


def _filename_fields(path: Path) -> tuple[str | None, str, str | None]:
    base = path.stem
    match = _DATED_NAME_RE.match(base)
    if not match:
        return None, base, None
    stamp = match.group("stamp")
    try:
        created = datetime.strptime(stamp, "%Y-%m-%d-%H-%M-%S").strftime(
            "%Y-%m-%d %H:%M:%S"
        )
    except ValueError:
        created = None
    return match.group("id"), match.group("slug"), created


@lru_cache(maxsize=4096)
def _cached_fields(path_str: str, mtime_ns: int, size: int) -> dict[str, str]:
    """Parse frontmatter once per file version.

    The list endpoint polls while an identity is live.  Keying on stat data
    avoids rereading hundreds of unchanged files every two seconds.
    """
    del mtime_ns, size  # used only as cache-key version stamps
    try:
        text = Path(path_str).read_text(encoding="utf-8", errors="replace")
        return _frontmatter(text)
    except OSError:
        return {}


def memory_info(path: Path) -> dict[str, Any]:
    """Build the list-endpoint representation for one memory file."""
    stat = path.stat()
    fields = _cached_fields(str(path), stat.st_mtime_ns, stat.st_size)
    filename_id, slug, filename_created = _filename_fields(path)
    created = fields.get("created")
    if created:
        try:
            datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            created = None
    return {
        "name": path.name,
        "mtime": stat.st_mtime,
        "id": fields.get("id") or filename_id,
        "summary": fields.get("summary") or None,
        "type": fields.get("type") or "memory",
        "created": created or filename_created,
        "slug": slug,
    }


def _sort_key(info: dict[str, Any]) -> tuple[float, str]:
    created = info.get("created")
    if isinstance(created, str):
        try:
            parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
            timestamp = parsed.timestamp()
            return timestamp, info["name"]
        except (ValueError, OverflowError):
            pass
    return float(info["mtime"]), info["name"]


def list_memories(identity_dir: Path) -> list[dict[str, Any]]:
    mem_dir = identity_dir / "memories"
    if not mem_dir.is_dir():
        return []
    result = []
    for path in mem_dir.glob("*.md"):
        try:
            result.append(memory_info(path))
        except OSError:
            # A file may disappear while a live identity is updating it.
            continue
    result.sort(key=_sort_key, reverse=True)
    return result
