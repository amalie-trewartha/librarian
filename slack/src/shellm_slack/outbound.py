"""Mind log -> Slack.

Follows the identity's root trajectory and forwards message steps the
identity addressed to a slack-* conversation name. The bridge's own
inbound steps have a slack-* `from` (not the identity), so they never
match — no echo loop.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from . import mindlog, naming
from .config import Config
from .slackfmt import chunk, to_mrkdwn
from .state import ActiveThreads

log = logging.getLogger(__name__)


def run(
    cfg: Config,
    client: Any,
    threads: ActiveThreads,
    stop_event: threading.Event,
) -> None:
    traj = mindlog.find_trajectory(cfg.identity_dir)
    cursor = cfg.state_dir / "cursor"
    log.info("following %s", traj)
    for step in mindlog.follow(traj, cursor, should_stop=stop_event.is_set):
        if step.get("type") != "message" or step.get("from") != cfg.identity:
            continue
        to = step.get("to")
        if not naming.is_slack_name(to):
            continue
        conv = naming.decode(to)
        text = to_mrkdwn(str(step.get("content") or "")).strip()
        if not text:
            continue
        threads.touch(conv.channel, conv.thread_ts)
        for part in chunk(text):
            try:
                client.chat_postMessage(
                    channel=conv.channel,
                    thread_ts=conv.thread_ts,
                    text=part,
                    unfurl_links=False,
                )
            except Exception:
                log.exception("chat_postMessage failed for %s", to)
                break


def start(
    cfg: Config,
    client: Any,
    threads: ActiveThreads,
    stop_event: threading.Event,
) -> threading.Thread:
    thread = threading.Thread(
        target=run,
        args=(cfg, client, threads, stop_event),
        name="slack-outbound",
        daemon=True,
    )
    thread.start()
    return thread
