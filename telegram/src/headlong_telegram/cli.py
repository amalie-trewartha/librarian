"""Run the Telegram bridge for a shellm identity.

Usage: headlong-telegram-bridge [ROOT]

ROOT is the directory the web server serves (contains .identities/);
defaults to the current directory. Configuration comes from the
environment — see config.py.
"""

import argparse
import logging
import sys
import threading
from pathlib import Path

from . import config, outbound
from .allowlist import Allowlist
from .api import Bot
from .inbound import Inbound


def main() -> None:
    parser = argparse.ArgumentParser(prog="headlong-telegram-bridge", description=__doc__)
    parser.add_argument("root", nargs="?", default=".", help="Serve root (contains .identities/)")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

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
