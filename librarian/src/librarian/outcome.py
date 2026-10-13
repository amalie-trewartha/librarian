"""The deterministic wake outcome rule and the phase map.

The runtime decides, from artifacts; the model's self-report is never
evidence of success. See design/librarian.md, "Outcomes".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import model
from .triggers import normalize_signature

PHASE_MAP = {"build": "building", "harden": "reviewing", "final": "handoff", "ended": "handoff", "open": "building"}
ULID_RE = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")
_VERDICT_RE = re.compile(r"\b(SURVIVES|BROKEN|UNVERIFIABLE)\b")


def map_phase(project_phase: str, ritual: Optional[str], signals: str, debugging: bool = False) -> str:
    phase = PHASE_MAP.get((project_phase or "").strip(), "building")
    kind = (ritual or "").split(" ", 1)[0]
    if kind in ("daily", "weekly"):
        phase = "reviewing"
    elif kind == "final":
        phase = "handoff"
    if re.search(r"^- (STALL|DELIVERABLE MISSING)", signals or "", re.M):
        phase = "planning"
    if debugging:
        phase = "debugging"
    return phase if phase in model.PHASES else "building"


@dataclass
class WakeEvidence:
    rc: int = 0
    stderr_tail: str = ""
    final: str = ""
    ritual: Optional[str] = None
    ritual_output_written: bool = False
    journal_dirty: bool = False
    dirty_files: list[str] = field(default_factory=list)
    review_verdicts: list[dict] = field(default_factory=list)  # {file, verdict, ids}
    recurred: list[dict] = field(default_factory=list)  # {signature, skill_id}
    cited_ids: list[str] = field(default_factory=list)


def decide_outcome(ev: WakeEvidence) -> tuple[str, str, dict]:
    """(outcome, criterion, per-id overrides). First match wins; verdicts also set overrides."""
    overrides: dict[str, str] = {}
    for v in ev.review_verdicts:
        for nid in v.get("ids", []):
            if v["verdict"] == "SURVIVES":
                overrides[nid] = "success"
            elif v["verdict"] == "BROKEN":
                overrides[nid] = "failure"
    for r in ev.recurred:
        overrides[r["skill_id"]] = "failure"
    if ev.ritual and ev.ritual_output_written:
        kind = ev.ritual.split(" ", 1)[0]
        return "success", f"ritual {kind} output written", overrides
    survived = [v for v in ev.review_verdicts if v["verdict"] == "SURVIVES" and v.get("ids")]
    broken = [v for v in ev.review_verdicts if v["verdict"] == "BROKEN" and v.get("ids")]
    if survived:
        return "success", f"adversary review SURVIVES: {survived[0]['file']}", overrides
    if broken:
        return "failure", f"adversary review BROKEN: {broken[0]['file']}", overrides
    if "Max iterations" in (ev.stderr_tail or ""):
        return "failure", "step cap reached without FINAL", overrides
    if ev.rc != 0:
        return "failure", f"run failed (rc={ev.rc})", overrides
    if ev.recurred:
        return "failure", f"failure recurred: {ev.recurred[0]['signature']}", overrides
    if ev.journal_dirty and ev.final.strip():
        return "partial", "journal entry + FINAL (unverified)", overrides
    if ev.final.strip():
        return "partial", "FINAL without journal entry", overrides
    return "unknown", "no measurable artifact", overrides


def find_ulids(text: str) -> list[str]:
    out: list[str] = []
    for m in ULID_RE.findall(text or ""):
        if m not in out:
            out.append(m)
    return out


def review_verdicts(files: dict[str, str]) -> list[dict]:
    """``{path: text}`` of new or changed review files → verdicts with the ids each cites."""
    out = []
    for path, text in files.items():
        verdicts = _VERDICT_RE.findall(text or "")
        if not verdicts:
            continue
        verdict = "BROKEN" if "BROKEN" in verdicts else "SURVIVES" if "SURVIVES" in verdicts else "UNVERIFIABLE"
        out.append({"file": path, "verdict": verdict, "ids": find_ulids(text)})
    return out


# ── trajectory reading ───────────────────────────────────────────────────────


def error_signatures(steps: list[dict]) -> list[str]:
    sigs: list[str] = []
    for s in steps:
        if s.get("type") != "shell-output":
            continue
        try:
            exit_code = int(s.get("exit", 0))
        except (TypeError, ValueError):
            exit_code = 0
        if exit_code == 0:
            continue
        text = (s.get("stderr") or "").strip() or (s.get("stdout") or "").strip()
        lines = [ln for ln in text.splitlines() if ln.strip()]
        # The last non-empty line usually names the error; fall back to the first.
        pick = ""
        for ln in reversed(lines):
            if re.search(r"error|not found|failed|denied|refused|No such|Traceback|Exception|exit", ln, re.I):
                pick = ln
                break
        if not pick and lines:
            pick = lines[-1]
        sig = normalize_signature(pick)
        if sig and sig not in sigs:
            sigs.append(sig)
    return sigs


_CMD_FAMILY = re.compile(r"^\s*(?:sudo\s+|env\s+\S+\s+)*([A-Za-z0-9_.\-/]+)")


def command_family(cmd: str) -> str:
    for line in (cmd or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or s.startswith("FINAL") or s.startswith("traj "):
            continue
        m = _CMD_FAMILY.match(s)
        if m:
            return m.group(1).rsplit("/", 1)[-1]
    return ""


def detect_resolved_failures(steps: list[dict], min_failures: int = 2) -> list[dict]:
    """A signature that failed ≥ ``min_failures`` times, after which the same command family succeeded."""
    fails: dict[str, dict] = {}
    pending_cmd = ""
    order: list[tuple[str, str, int, str]] = []  # (kind, signature|family, index, step_id)
    for i, s in enumerate(steps):
        t = s.get("type")
        if t == "reasoning":
            pending_cmd = s.get("cmd") or ""
            continue
        if t != "shell-output":
            continue
        fam = command_family(pending_cmd)
        try:
            exit_code = int(s.get("exit", 0))
        except (TypeError, ValueError):
            exit_code = 0
        if exit_code != 0:
            sigs = error_signatures([s])
            sig = sigs[0] if sigs else f"{fam} exit {exit_code}"
            d = fails.setdefault(sig, {"count": 0, "family": fam, "first": s.get("step_id"), "first_i": i, "resolved": None})
            d["count"] += 1
            if not d["family"]:
                d["family"] = fam
            order.append(("fail", sig, i, s.get("step_id", "")))
        else:
            order.append(("ok", fam, i, s.get("step_id", "")))
    out = []
    for sig, d in fails.items():
        if d["count"] < min_failures:
            continue
        for kind, fam, i, sid in order:
            if kind == "ok" and fam and fam == d["family"] and i > d["first_i"]:
                d["resolved"] = sid
                out.append({"signature": sig, "family": fam, "count": d["count"], "span": [d["first"], sid]})
                break
    return out
