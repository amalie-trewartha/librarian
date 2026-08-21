from headlong_telegram.allowlist import Allowlist


def test_approve_revoke_round_trip(tmp_path):
    al = Allowlist(tmp_path / "allowlist.json")
    assert not al.is_approved(7)
    al.approve(7, "Dana")
    assert al.is_approved(7)
    assert al.revoke(7)
    assert not al.is_approved(7)
    assert not al.revoke(7)


def test_persistence(tmp_path):
    path = tmp_path / "allowlist.json"
    Allowlist(path).approve(7, "Dana")
    assert Allowlist(path).is_approved(7)


def test_pending_notifies_once_per_interval(tmp_path):
    al = Allowlist(tmp_path / "allowlist.json")
    assert al.note_pending(9, "Stranger")
    assert not al.note_pending(9, "Stranger")  # rate limited


def test_denied_never_renotifies(tmp_path):
    al = Allowlist(tmp_path / "allowlist.json")
    al.note_pending(9, "Stranger")
    al.deny(9)
    assert not al.note_pending(9, "Stranger")
    assert not al.is_approved(9)


def test_approve_clears_pending_and_denied(tmp_path):
    al = Allowlist(tmp_path / "allowlist.json")
    al.note_pending(9, "Dana Kim")
    al.deny(9)
    al.approve(9)
    assert al.is_approved(9)


def test_approve_keeps_pending_label(tmp_path):
    al = Allowlist(tmp_path / "allowlist.json")
    al.note_pending(9, "Dana Kim")
    al.approve(9)
    assert "Dana Kim" in al.summary()


def test_corrupt_file_starts_empty(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text("not json{")
    al = Allowlist(path)
    assert not al.is_approved(1)
    al.approve(1)
    assert Allowlist(path).is_approved(1)
