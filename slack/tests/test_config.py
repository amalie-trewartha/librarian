"""Identity selection: the env var, then the `default` symlink, then an error."""

import pytest

from headlong_slack import config


def _identity(root, name):
    d = root / ".identities" / name
    d.mkdir(parents=True)
    (d / "info.txt").write_text("an identity\n")
    return d


@pytest.fixture(autouse=True)
def _tokens(monkeypatch):
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-test")
    monkeypatch.setenv("SLACK_APP_TOKEN", "xapp-test")
    monkeypatch.delenv("HEADLONG_SLACK_IDENTITY", raising=False)
    monkeypatch.delenv("SHELLM_SLACK_IDENTITY", raising=False)


def test_falls_back_to_the_default_symlink(tmp_path):
    _identity(tmp_path, "ada")
    (tmp_path / ".identities" / "default").symlink_to("ada")

    assert config.load(tmp_path).identity == "ada"


def test_env_var_wins_over_the_default_symlink(tmp_path, monkeypatch):
    _identity(tmp_path, "ada")
    _identity(tmp_path, "bo")
    (tmp_path / ".identities" / "default").symlink_to("ada")
    monkeypatch.setenv("HEADLONG_SLACK_IDENTITY", "bo")

    assert config.load(tmp_path).identity == "bo"


def test_no_var_and_no_default_names_the_variable(tmp_path):
    _identity(tmp_path, "ada")

    with pytest.raises(SystemExit) as exc:
        config.load(tmp_path)
    assert "HEADLONG_SLACK_IDENTITY" in str(exc.value)
