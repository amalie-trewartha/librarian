"""Memory metadata parsing and API tests."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from headlong_web import memories
from headlong_web.server import create_app


def _identity_root(tmp_path: Path) -> tuple[Path, Path]:
    identity = tmp_path / ".identities" / "keeper"
    identity.mkdir(parents=True)
    root_traj = "aaaaaaaa-1111-4111-8111-111111111111"
    (identity / "info.txt").write_text(
        f"name=keeper\ncreated=2026-08-01T00:00:00\nroot_trajectory={root_traj}\n"
    )
    traj_dir = identity / "trajectories" / "aaaaaaaa-root"
    traj_dir.mkdir(parents=True)
    (traj_dir / "trajectory.jsonl").write_text(
        json.dumps({"type": "trajectory", "step_id": root_traj, "ts": "t0"}) + "\n"
    )
    (identity / "memories").mkdir()
    return tmp_path, identity


def test_memory_info_reads_frontmatter_and_filename(tmp_path: Path):
    path = tmp_path / "2026-08-20-12-34-56_deadbeef_use-a-small-parser.md"
    path.write_text(
        "---\n"
        "id: deadbeef\n"
        'summary: "Use a small parser: keep the format legible"\n'
        "type: lesson\n"
        "created: '2026-08-20 12:34:56'\n"
        "updated:\n"
        "  - 2026-08-21 09:00:00\n"
        "---\n\nBody\n"
    )

    info = memories.memory_info(path)

    assert info["id"] == "deadbeef"
    assert info["summary"] == "Use a small parser: keep the format legible"
    assert info["type"] == "lesson"
    assert info["created"] == "2026-08-20 12:34:56"
    assert info["slug"] == "use-a-small-parser"


def test_memory_info_falls_back_for_legacy_and_plain_names(tmp_path: Path):
    legacy = tmp_path / "2026-08-19-10-20-30_old-format.md"
    legacy.write_text("A memory without frontmatter.\n")
    plain = tmp_path / "lessons.md"
    plain.write_text("---\ntype:\ncreated: not-a-date\n---\n")

    legacy_info = memories.memory_info(legacy)
    plain_info = memories.memory_info(plain)

    assert legacy_info | {"mtime": 0} == {
        "name": legacy.name,
        "mtime": 0,
        "id": None,
        "summary": None,
        "type": "memory",
        "created": "2026-08-19 10:20:30",
        "slug": "old-format",
    }
    assert plain_info["slug"] == "lessons"
    assert plain_info["type"] == "memory"
    assert plain_info["created"] is None


def test_unclosed_frontmatter_is_treated_as_plain_markdown(tmp_path: Path):
    path = tmp_path / "unclosed.md"
    path.write_text("---\nsummary: This block never closes\nBody text\n")

    info = memories.memory_info(path)

    assert info["summary"] is None
    assert info["type"] == "memory"


def test_memories_endpoint_returns_metadata_sorted_by_created(tmp_path: Path):
    root, identity = _identity_root(tmp_path)
    mem_dir = identity / "memories"
    (mem_dir / "older.md").write_text(
        "---\nsummary: Older note\ntype: note\ncreated: 2026-08-10 09:00:00\n---\n"
    )
    (mem_dir / "newer.md").write_text(
        "---\nid: abc12345\nsummary: New preference\ntype: preference\n"
        "created: 2026-08-20 09:00:00\n---\n"
    )

    response = TestClient(create_app(root)).get(
        "/api/identities/.identities~keeper/memories"
    )

    assert response.status_code == 200
    payload = response.json()
    assert [item["name"] for item in payload] == ["newer.md", "older.md"]
    assert payload[0] | {"mtime": 0} == {
        "name": "newer.md",
        "mtime": 0,
        "id": "abc12345",
        "summary": "New preference",
        "type": "preference",
        "created": "2026-08-20 09:00:00",
        "slug": "newer",
    }


def test_memories_endpoint_handles_missing_directory(tmp_path: Path):
    root, _identity = _identity_root(tmp_path)
    (root / ".identities" / "keeper" / "memories").rmdir()

    response = TestClient(create_app(root)).get(
        "/api/identities/.identities~keeper/memories"
    )

    assert response.status_code == 200
    assert response.json() == []


def test_memory_metadata_cache_refreshes_when_file_changes(tmp_path: Path):
    path = tmp_path / "memory.md"
    path.write_text("---\nsummary: First\n---\n")
    assert memories.memory_info(path)["summary"] == "First"

    path.write_text("---\nsummary: A longer second value\n---\n")

    assert memories.memory_info(path)["summary"] == "A longer second value"
