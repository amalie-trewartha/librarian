"""The deterministic wake outcome rule and the phase map.

The runtime decides, from artifacts; the model's self-report is never
evidence of success. See design/librarian.md, "Outcomes".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from . import model

_SIG_NUM = re.compile(r"\b\d+(?:\.\d+)?\b")
_SIG_HEX = re.compile(r"\b(?:0x)?[0-9a-f]{6,}\b", re.I)
_SIG_PATH = re.compile(r"(?:/[\w.\-]+){2,}")
_SIG_WS = re.compile(r"\s+")
# A claims file's numbered claims: "C1: ...", "C1. ...", "- C1 ...", "**C1**: ...".
_CLAIM_TEXT_RE = re.compile(r"^[ \t>*|-]*\**(C\d+[a-z]?)\**[ \t]*[:.)|-]?[ \t]*(.+?)[ \t]*$", re.M)


def normalize_signature(line: str) -> str:
    """First meaningful line of an error, with digits, hex and paths normalized."""
    first = ""
    for ln in (line or "").splitlines():
        if ln.strip():
            first = ln.strip()
            break
    first = _SIG_PATH.sub("<path>", first)
    first = _SIG_HEX.sub("<hex>", first)
    first = _SIG_NUM.sub("<n>", first)
    return _SIG_WS.sub(" ", first)[:200]


def parse_claims(text: str) -> dict[str, str]:
    """A claims file's claims by label: the first line of each "C<n>" item, with any
    continuation lines up to the next item or blank line."""
    out: dict[str, str] = {}
    lines = (text or "").splitlines()
    cur: Optional[str] = None
    for ln in lines:
        m = _CLAIM_TEXT_RE.match(ln)
        if m and m.group(2) and not re.match(r"^(SURVIVES|BROKEN|WEAKENED|UNVERIFIABLE)\b", m.group(2)):
            cur = m.group(1)
            if cur not in out:
                out[cur] = m.group(2).strip()
            else:
                cur = None
            continue
        if cur and ln.strip() and not ln.strip().startswith(("#", "Lessons applied")):
            if len(out[cur]) < 1200:
                out[cur] += " " + ln.strip()
        else:
            cur = None
    return out

PHASE_MAP = {"build": "building", "harden": "reviewing", "final": "handoff", "ended": "handoff", "open": "building"}
ULID_RE = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")
_VERDICT_RE = re.compile(r"\b(SURVIVES|BROKEN|UNVERIFIABLE)\b")
# A review that judged several claims names each verdict's memories on its own line.
_MEMORIES_LINE_RE = re.compile(r"^\s*Memories\s+(SURVIVES|BROKEN|UNVERIFIABLE)\s*:(.*)$", re.M)
# A claims file sent for review names the lessons its work applied, before any verdict exists.
_LESSONS_LINE_RE = re.compile(r"^\s*Lessons applied\s*:(.*)$", re.M | re.I)
# The reviewer's verdict on each claim: "- C2: BROKEN [basis] posted fare used as paid fare".
_CLAIM_LINE_RE = re.compile(r"^[ \t>*|-]*\**(C\d+[a-z]?)\**[ \t]*[:.)|-][ \t]*\**(SURVIVES|BROKEN|WEAKENED|UNVERIFIABLE)\**[ \t]*(?:\|[ \t]*)?(?:\[[ \t]*(?:fail:)?([A-Za-z-]+)[ \t]*\]|(?:fail:)?([a-z-]+)[ \t]*\|)?", re.M)
# An older form: one "Failure class: basis, stale" line for the whole review.
_FAILURE_LINE_RE = re.compile(r"^\W*Failure class(?:es)?\W*:(.*)$", re.M | re.I)
NOT_STANDING = ("BROKEN", "WEAKENED")
# shellm's own death when the model API gives up (HTTP 429/5xx after its retries): an outage, not the mind's work.
_MODEL_API_FAILURE_RE = re.compile(r"\bllm failed\b|\bAPI error \(HTTP (?:429|5\d\d)\)|transient API failure")


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
                overrides.setdefault(nid, "success")
            elif v["verdict"] == "BROKEN":
                overrides[nid] = "failure"
    if ev.ritual and ev.ritual_output_written:
        kind = ev.ritual.split(" ", 1)[0]
        return "success", f"ritual {kind} output written", overrides
    survived = [v for v in ev.review_verdicts if v["verdict"] == "SURVIVES" and v.get("ids")]
    broken = [v for v in ev.review_verdicts if v["verdict"] == "BROKEN" and v.get("ids")]
    # A review judges the memories it names (the overrides above), not this wake's pack: the rest
    # of the pack learns nothing, so the wake itself closes partial.
    if survived and broken:
        return "partial", f"adversary review mixed: {survived[0]['file']}", overrides
    if survived:
        return "partial", f"adversary review SURVIVES: {survived[0]['file']}", overrides
    if broken:
        return "partial", f"adversary review BROKEN: {broken[0]['file']}", overrides
    if "Max iterations" in (ev.stderr_tail or ""):
        return "failure", "step cap reached without FINAL", overrides
    if ev.rc != 0 and _MODEL_API_FAILURE_RE.search(ev.stderr_tail or ""):
        # Cut off mid-run by the model API: no evidence about the pack either way.
        return "partial", f"run cut off by model API failure (rc={ev.rc})", overrides
    if ev.rc != 0:
        return "failure", f"run failed (rc={ev.rc})", overrides
    # A recurred error signature gives no credit: in run B its only hit was a guard script's
    # intended MISS line, which blamed the whole pack. It is reported, not scored.
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
        labeled = _MEMORIES_LINE_RE.findall(text or "")
        if labeled:
            for verdict, rest in labeled:
                out.append({"file": path, "verdict": verdict, "ids": find_ulids(rest)})
            continue
        verdicts = _VERDICT_RE.findall(text or "")
        if not verdicts:
            continue
        verdict = "BROKEN" if "BROKEN" in verdicts else "SURVIVES" if "SURVIVES" in verdicts else "UNVERIFIABLE"
        out.append({"file": path, "verdict": verdict, "ids": find_ulids(text)})
    return out


def applied_lessons(text: str) -> list[str]:
    """The ids on a text's ``Lessons applied:`` lines."""
    out: list[str] = []
    for rest in _LESSONS_LINE_RE.findall(text or ""):
        for i in find_ulids(rest):
            if i not in out:
                out.append(i)
    return out


def _fail_class(raw: str) -> Optional[str]:
    c = model.normalize_tag((raw or "").strip(" `*_.").split("(")[0].strip().removeprefix("fail:"))
    if not c or c in ("none", "n-a", "na"):
        return None
    return c if c in model.DEFAULT_FAIL else "other"


def claim_verdicts(text: str) -> list[dict]:
    """The reviewer's per-claim verdicts: [{claim, verdict, class}], each claim once (its first line).
    A claim that does not stand (BROKEN, WEAKENED) without a known class gets 'other'."""
    out: dict[str, dict] = {}
    for claim, verdict, cls, cell in _CLAIM_LINE_RE.findall(text or ""):
        cls = cls or cell
        if claim in out:
            continue
        c = _fail_class(cls) if cls else None
        if verdict in NOT_STANDING and c is None:
            c = "other"
        out[claim] = {"claim": claim, "verdict": verdict, "class": c if verdict in NOT_STANDING else None}
    return list(out.values())


def failure_classes(text: str) -> list[str]:
    """The failure classes a review names, most frequent first, each once: from its claim
    verdicts, else from a "Failure class:" line; an unknown name counts as 'other'."""
    counts: dict[str, int] = {}
    for v in claim_verdicts(text):
        if v["class"]:
            counts[v["class"]] = counts.get(v["class"], 0) + 1
    if counts:
        return [c for c, _ in sorted(counts.items(), key=lambda kv: -kv[1])]
    out: list[str] = []
    for m in _FAILURE_LINE_RE.finditer(text or ""):
        for raw in re.split(r"[,;/|]| and ", m.group(1)):
            c = _fail_class(raw)
            if c and c not in out:
                out.append(c)
    return out


def review_outcome(verdicts: list[dict], claims: Optional[list[dict]] = None) -> Optional[str]:
    """One review file's result for the lessons its work applied: success when every claim
    the reviewer judged survived, failure when none stood, else none (mixed). The reviewer's
    claim verdicts decide when there are any; else the file's verdict lines."""
    if claims:
        vs = {c["verdict"] for c in claims} - {"UNVERIFIABLE"}
        if vs == {"SURVIVES"}:
            return "success"
        if vs and vs <= set(NOT_STANDING):
            return "failure"
        return None
    vs = {v["verdict"] for v in verdicts} - {"UNVERIFIABLE"}
    if vs == {"SURVIVES"}:
        return "success"
    if vs == {"BROKEN"}:
        return "failure"
    return None


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
        # A line that was only a number or a path normalizes to "<n>": it names no error
        # (run B's one such capture cleared on a skill about something else).
        if len(re.sub(r"<\w+>|[^A-Za-z]", "", sig or "")) < 3:
            continue
        if sig not in sigs:
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
