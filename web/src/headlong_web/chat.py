"""Chat view over the mind log: filter message steps from trajectory.jsonl.

Served from the trajectory cache's compact chat index — chat polls used
to re-parse the whole jsonl per request, which on audel's 590MB mind log
meant ~3.5GB of transient dicts per poll and was a main driver of the
2026-08-13 OOM incident.
"""

from typing import Any

from headlong_web.trajectory import CHAT_MESSAGE_TYPES as MESSAGE_TYPES


def chat_view(
    steps: list[dict[str, Any]],
    identity_name: str,
    tail: int = 200,
    with_name: str | None = None,
) -> dict:
    """Messages plus per-inbound-step outcomes.

    Outcomes map a sent message's step_id to what the identity did with it:
    "replied" (a reply stamps reply_to), "no-reply" (the thinker's
    decision:"no-reply" observation stamps trigger_step), or "failed" (its
    reply-failed observation). Absent means still undecided — which is what
    a truthful typing indicator needs.

    `steps` is the cache's compact chat index (trajectory.CACHE.chat_steps):
    message steps plus trigger-stamped observations, small fields only.
    """
    messages = []
    outcomes: dict[str, str] = {}
    for raw in steps:
        step_type = raw.get("type")
        if step_type == "observation":
            trigger = raw.get("trigger_step")
            if trigger:
                if raw.get("decision") == "no-reply":
                    outcomes[trigger] = "no-reply"
                elif str(raw.get("content") or "").startswith("reply failed"):
                    outcomes[trigger] = "failed"
            continue
        if step_type not in MESSAGE_TYPES:
            continue
        content = raw.get("content")
        if not content:
            continue
        if step_type == "message":
            from_name = raw.get("from") or "unknown"
            to_name = raw.get("to") or ""
        elif step_type == "human-msg":
            from_name = raw.get("from") or "you"
            to_name = identity_name
        else:  # agent-msg
            from_name = identity_name
            to_name = raw.get("to") or ""
        reply_to = raw.get("reply_to")
        if reply_to:
            outcomes[reply_to] = "replied"
        if with_name is not None and with_name not in (from_name, to_name):
            continue
        messages.append(
            {
                "ts": raw.get("ts"),
                "step_id": raw.get("step_id"),
                "from": from_name,
                "to": to_name,
                "content": content,
                "reply_to": reply_to,
                "filename": raw.get("filename"),
            }
        )
    return {"messages": messages[-tail:], "outcomes": outcomes}


def chat_messages(
    steps: list[dict[str, Any]],
    identity_name: str,
    tail: int = 200,
    with_name: str | None = None,
) -> list[dict]:
    return chat_view(steps, identity_name, tail, with_name)["messages"]
