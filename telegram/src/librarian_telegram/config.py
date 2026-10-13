"""Bridge configuration from environment variables.

All settings come from the process environment. In production the systemd
unit loads /etc/shellm/telegram.env (root-owned, mode 600) — deliberately
NOT the shared root .env, so the bot token never enters the agent's
environment. See telegram/README.md.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    serve_root: Path
    identity: str
    identity_dir: Path
    bot_token: str
    admin_id: int
    web_url: str
    state_dir: Path

    @property
    def identity_api_id(self) -> str:
        """Identity id for the web API: root-relative path with / -> ~."""
        rel = self.identity_dir.relative_to(self.serve_root)
        return str(rel).replace("/", "~")


def _default_identity(serve_root: Path) -> str:
    """The identity the `default` symlink points at, as `persona` resolves it.

    The immediate link target, not the end of the chain: an identity dir may
    itself be a symlink elsewhere, and its name here is the one `identity
    default` recorded.
    """
    for base in (".identities", "identities"):
        link = serve_root / base / "default"
        if link.is_symlink():
            name = link.readlink().name
            # A dangling default is its own error: passing the name on would
            # surface as "identity not found ... identity new <name>", advice
            # that creates a second identity instead of fixing the link.
            if not (serve_root / base / name).is_dir():
                raise SystemExit(
                    f"headlong-telegram-bridge: the default identity link {link} "
                    f"points at '{name}', which is not an identity under "
                    f"{serve_root / base}. Repoint it with: identity default <name>"
                )
            return name
    raise SystemExit(
        "headlong-telegram-bridge: no identity given and no default set "
        f"under {serve_root} (looked for .identities/default and "
        "identities/default). Set HEADLONG_TELEGRAM_IDENTITY, or point the "
        "default at one with: identity default <name>"
    )


def _find_identity_dir(serve_root: Path, name: str) -> Path:
    for base in (".identities", "identities"):
        candidate = serve_root / base / name
        if (candidate / "info.txt").is_file():
            return candidate
    raise SystemExit(
        f"headlong-telegram-bridge: identity '{name}' not found under {serve_root} "
        "(looked in .identities/ and identities/). Create it with: identity new "
        + name
    )


def load(serve_root: Path) -> Config:
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not bot_token:
        raise SystemExit("headlong-telegram-bridge: TELEGRAM_BOT_TOKEN is required")
    admin_raw = os.environ.get("TELEGRAM_ADMIN_ID", "")
    if not admin_raw.isdigit():
        raise SystemExit(
            "headlong-telegram-bridge: TELEGRAM_ADMIN_ID is required (your numeric "
            "Telegram user id — message the bot once and check the bridge log)"
        )
    # HEADLONG_* is canonical; SHELLM_* accepted as a legacy fallback until the
    # deployed boxes migrate their env files.
    identity = (
        os.environ.get("HEADLONG_TELEGRAM_IDENTITY")
        or os.environ.get("SHELLM_TELEGRAM_IDENTITY")
        or _default_identity(serve_root)
    )
    identity_dir = _find_identity_dir(serve_root, identity)
    state_dir = Path(
        os.environ.get("HEADLONG_TELEGRAM_STATE_DIR")
        or os.environ.get("SHELLM_TELEGRAM_STATE_DIR")
        or identity_dir / "run" / "telegram-bridge"
    )
    state_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        serve_root=serve_root,
        identity=identity,
        identity_dir=identity_dir,
        bot_token=bot_token,
        admin_id=int(admin_raw),
        web_url=(
            os.environ.get("HEADLONG_WEB_URL")
            or os.environ.get("SHELLM_WEB_URL")
            or "http://127.0.0.1:8080"
        ).rstrip("/"),
        state_dir=state_dir,
    )
