"""Thinker sync: drift detection, pull semantics, per-identity state kept."""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from headlong_web import thinker_sync
from headlong_web.server import create_app

ROOT_TRAJ = "fafafafa-1111-4111-8111-111111111111"


@pytest.fixture
def bundled(tmp_path: Path, monkeypatch) -> Path:
    src = tmp_path / "bundled"
    mono = src / "monolith"
    mono.mkdir(parents=True)
    (mono / "step").write_text("#!/bin/bash\necho v2\n")
    (mono / "prompt.md").write_text("routing menu v2\n")
    (mono / "subscriptions.jsonl").write_text('{"types":["idle"],"trigger_self":true}\n')
    lib = src / "_lib"
    lib.mkdir()
    (lib / "common.sh").write_text("common v2\n")
    monkeypatch.setenv("SHELLM_WEB_THINKERS_SRC", str(src))
    return src


@pytest.fixture
def identity(tmp_path: Path) -> Path:
    ident = tmp_path / ".identities" / "bot"
    thinker = ident / "thinkers" / "monolith"
    thinker.mkdir(parents=True)
    (ident / "info.txt").write_text(f"name=bot\nroot_trajectory={ROOT_TRAJ}\n")
    (thinker / "step").write_text("#!/bin/bash\necho v1\n")
    (thinker / "prompt.md").write_text("routing menu v2\n")
    (thinker / "subscriptions.jsonl").write_text(
        f'{{"types":["idle"],"trigger_self":true,"traj_id":"{ROOT_TRAJ}"}}\n'
    )
    lib = ident / "thinkers" / "_lib"
    lib.mkdir()
    (lib / "common.sh").write_text("common v2\n")
    return ident


def test_status_reports_drift(bundled: Path, identity: Path):
    result = thinker_sync.status(identity)
    by_name = {t["name"]: t for t in result["thinkers"]}
    assert by_name["monolith"]["status"] == "outdated"
    assert by_name["monolith"]["changed_files"] == ["step"]
    assert by_name["_lib"]["status"] == "in_sync"


def test_local_only_and_not_installed(bundled: Path, identity: Path):
    (identity / "thinkers" / "homegrown").mkdir()
    (bundled / "actor").mkdir()
    (bundled / "actor" / "step").write_text("#!/bin/bash\n")
    result = thinker_sync.status(identity)
    by_name = {t["name"]: t for t in result["thinkers"]}
    assert by_name["homegrown"]["status"] == "local_only"
    assert by_name["actor"]["status"] == "not_installed"


def test_sync_updates_code_but_keeps_identity_state(bundled: Path, identity: Path):
    subs_before = (identity / "thinkers" / "monolith" / "subscriptions.jsonl").read_text()
    (identity / "thinkers" / "monolith" / "disabled").write_text("keep me\n")
    result = thinker_sync.sync(identity, ["monolith"])
    assert result["results"] == [
        {"name": "monolith", "action": "updated", "files": ["step"]}
    ]
    step = identity / "thinkers" / "monolith" / "step"
    assert step.read_text().endswith("echo v2\n")
    assert os.access(step, os.X_OK)
    assert (identity / "thinkers" / "monolith" / "subscriptions.jsonl").read_text() == subs_before
    assert (identity / "thinkers" / "monolith" / "disabled").read_text() == "keep me\n"
    assert thinker_sync.status(identity)["thinkers"][1]["status"] == "in_sync"


def test_sync_empty_names_pulls_all_outdated(bundled: Path, identity: Path):
    (bundled / "_lib" / "common.sh").write_text("common v3\n")
    result = thinker_sync.sync(identity, [])
    actions = {r["name"]: r["action"] for r in result["results"]}
    assert actions == {"_lib": "updated", "monolith": "updated"}


def test_install_injects_traj_id(bundled: Path, identity: Path):
    (bundled / "actor").mkdir()
    (bundled / "actor" / "step").write_text("#!/bin/bash\n")
    (bundled / "actor" / "subscriptions.jsonl").write_text('{"types":["action"]}\n')
    result = thinker_sync.sync(identity, ["actor"])
    assert result["results"][0]["action"] == "installed"
    sub = json.loads(
        (identity / "thinkers" / "actor" / "subscriptions.jsonl").read_text()
    )
    assert sub["traj_id"] == ROOT_TRAJ


def test_endpoints(bundled: Path, identity: Path, tmp_path: Path):
    client = TestClient(create_app(tmp_path))
    identity_id = ".identities~bot"
    body = client.get(f"/api/identities/{identity_id}/thinker-sync").json()
    assert {t["name"]: t["status"] for t in body["thinkers"]}["monolith"] == "outdated"

    resp = client.post(
        f"/api/identities/{identity_id}/thinker-sync", json={"names": ["monolith"]}
    )
    assert resp.status_code == 200
    assert resp.json()["results"][0]["action"] == "updated"

    bad = client.post(
        f"/api/identities/{identity_id}/thinker-sync", json={"names": ["../evil"]}
    )
    assert bad.status_code == 422
