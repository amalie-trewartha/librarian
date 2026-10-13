"""Run the Telegram bridge for a shellm identity.

Usage: headlong-telegram-bridge [ROOT]

ROOT is the directory the web server serves (contains .identities/);
defaults to the current directory. Configuration comes from the
environment — see config.py.
"""

import argparse
import logging
import re
import sys
import threading
from pathlib import Path

from . import config, outbound
from .allowlist import Allowlist
from .api import Bot
from .inbound import Inbound


# Every Bot API URL carries the token (https://api.telegram.org/bot<id>:<secret>/
# method). httpx logs one "HTTP Request: POST <url>" line per call at INFO, so
# the bridge was writing the token to journald fifty times an hour; an httpx
# exception message quotes the URL too. Redact it wherever a record is
# formatted, and keep httpx's per-request chatter out of the log altogether.
_TOKEN_RE = re.compile(r"bot\d+:[A-Za-z0-9_-]+")
_REDACTED = "bot<redacted>"


def redact(text: str) -> str:
    return _TOKEN_RE.sub(_REDACTED, text)


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def configure_logging(verbose: bool) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingFormatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)


def main() -> None:
    parser = argparse.ArgumentParser(prog="headlong-telegram-bridge", description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="Serve root (contains .identities/)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    configure_logging(args.verbose)

    serve_root = Path(args.root).resolve()
    if not serve_root.is_dir():
        raise SystemExit(f"Not a directory: {serve_root}")
    cfg = config.load(serve_root)

    bot = Bot(cfg.bot_token)
    me = bot.get_me()
    print(
        f"headlong-telegram-bridge: identity={cfg.identity} bot=@{me.get('username')} "
        f"admin={cfg.admin_id} web={cfg.web_url}",
        file=sys.stderr,
    )

    allowlist = Allowlist(cfg.state_dir / "allowlist.json")
    if not allowlist.is_approved(cfg.admin_id):
        allowlist.approve(cfg.admin_id, "admin")
    stop_event = threading.Event()
    outbound.start(cfg, bot, allowlist, stop_event)
    try:
        Inbound(cfg, bot, allowlist).run()  # blocks
    finally:
        stop_event.set()


if __name__ == "__main__":
    main()
