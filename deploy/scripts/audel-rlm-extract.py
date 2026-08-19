# audel-rlm-extract.py — one streaming pass over a mind log, counting RLM moves.
#
# "RLM" here means the recursive-language-model machinery: the mind invoking
# llm / shellm from inside its own bash, and manipulating its trajectory and
# memory programmatically (traj cat|search, mem search, recap) instead of
# only reacting to whatever was stuffed into its context window.
#
# Usage: python3 audel-rlm-extract.py <identity-dir | trajectory.jsonl>
# Output: one JSON object on stdout (aggregates only — safe for the 24KB
# SSM output cap after gzip+base64 by the caller).
#
# Everything is computed in ONE pass, line by line — mind logs are big and
# must never be slurped (see the bin/context head/tail lesson).

import glob
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

target = sys.argv[1]

if os.path.isdir(target):
    ident_dir = target
    path = None
    try:
        with open(os.path.join(ident_dir, "info.txt"), encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("root_trajectory="):
                    root = line.split("=", 1)[1].strip()
                    hits = glob.glob(os.path.join(
                        ident_dir, "trajectories", root[:8] + "-*", "trajectory.jsonl"))
                    if hits:
                        path = hits[0]
    except OSError:
        pass
    if not path:
        hits = sorted(glob.glob(os.path.join(ident_dir, "trajectories", "*", "trajectory.jsonl")))
        path = hits[0] if hits else None
    if not path:
        sys.stderr.write("no root trajectory found under " + ident_dir + "\n")
        sys.exit(1)
else:
    path = target

# ---------------------------------------------------------------------------
# Bash classification. We only look at the cmd field of reasoning steps —
# that is the bash the mind actually ran. Quoted strings and heredoc bodies
# are stripped first so a *thought about* llm (e.g. traj append --field
# content="I should try llm here") never counts as an *invocation of* llm.
# ---------------------------------------------------------------------------

TOOLS = {"llm", "shellm", "traj", "mem", "recap", "context"}
TRAJ_WRITE = {"new", "append", "fork", "merge"}
MEM_WRITE = {"add", "forget", "edit"}
# Wrappers whose next token is the real command.
SKIP_TOKENS = {"sudo", "command", "exec", "time", "nohup", "env", "xargs",
               "do", "then", "else", "if", "while", "until", "{", "!"}

SQ = re.compile(r"'[^']*'")
DQ = re.compile(r'"(?:\\.|[^"\\])*"')
HEREDOC = re.compile(r"<<-?\s*'?([A-Za-z_][A-Za-z0-9_]*)'?")
SEG_SPLIT = re.compile(r"[|;&`\n(]|\$\(")
ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def strip_heredocs(cmd):
    out, i, lines = [], 0, cmd.split("\n")
    while i < len(lines):
        out.append(lines[i])
        m = HEREDOC.search(lines[i])
        if m:
            delim = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != delim:
                i += 1
        i += 1
    return "\n".join(out)


def classify(cmd):
    """Return the set of RLM classes this bash block invokes."""
    text = strip_heredocs(cmd)
    text = SQ.sub("''", text)
    text = DQ.sub('""', text)
    classes = set()
    for seg in SEG_SPLIT.split(text):
        toks = seg.split()
        while toks and (ASSIGN.match(toks[0]) or toks[0] in SKIP_TOKENS
                        or (len(toks) > 1 and toks[0] == "timeout")):
            if toks[0] == "timeout":  # timeout [opts] DURATION cmd...
                toks = toks[1:]
                while toks and (toks[0].startswith("-") or re.match(r"^[0-9]", toks[0])):
                    toks = toks[1:]
            else:
                toks = toks[1:]
        if not toks:
            continue
        name = os.path.basename(toks[0])
        if name not in TOOLS:
            continue
        sub = toks[1] if len(toks) > 1 else ""
        if name == "traj":
            classes.add("traj_write" if sub in TRAJ_WRITE else "traj_read")
        elif name == "mem":
            classes.add("mem_write" if sub in MEM_WRITE else "mem_read")
        else:
            classes.add(name)
    # Direct pokes at the log file bypass the traj tool but are still
    # programmatic log manipulation.
    if "trajectory.jsonl" in text or "TRAJ_DIR" in text:
        classes.add("traj_read")
    return classes


OFFSET_FIX = re.compile(r"([+-][0-9]{2})([0-9]{2})$")


def day_of(ts):
    return (ts or "")[:10]


def pct(values):
    if not values:
        return None
    vs = sorted(values)

    def at(p):
        return vs[int(round(p / 100.0 * (len(vs) - 1)))]

    return {"n": len(vs), "p50": at(50), "p90": at(90), "p95": at(95), "max": vs[-1]}


# RLM classes = recursion + programmatic self-inspection. traj_write is the
# mind's ordinary step-appending mechanics, tracked but not counted as RLM.
RLM_CLASSES = ("llm", "shellm", "traj_read", "mem_read", "mem_write", "recap", "context")

type_counts = defaultdict(int)
monolith_types = defaultdict(int)
class_steps = defaultdict(int)            # class -> reasoning steps invoking it
class_runs = defaultdict(set)             # class -> run_ids
class_days = defaultdict(set)             # class -> days
class_out_bytes = defaultdict(list)       # class -> stdout bytes of the paired output
class_fail = defaultdict(int)             # class -> nonzero-exit outputs
daily = defaultdict(lambda: defaultdict(int))  # day -> {reasoning, <class>...}
log_at_traj_read = []                     # log bytes visible when a traj read ran
run_ids = set()
rlm_runs = set()
merge_count = 0
merge_sources = set()
shellm_run_count = 0
pending = {}                              # run_id -> classes awaiting shell-output
first_ts = last_ts = None
total = parsed = 0
bytes_so_far = 0

with open(path, encoding="utf-8", errors="replace") as fh:
    for line in fh:
        bytes_so_far += len(line.encode("utf-8", errors="replace"))
        line = line.strip()
        if not line:
            continue
        total += 1
        try:
            step = json.loads(line)
        except ValueError:
            continue
        parsed += 1
        t = step.get("type") or ""
        ts = step.get("ts") or ""
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        day = day_of(ts)
        rid = step.get("run_id") or ""
        type_counts[t] += 1
        if step.get("source") == "monolith":
            monolith_types[t] += 1
        if rid:
            run_ids.add(rid)
        if t == "shellm-run":
            shellm_run_count += 1
        elif t == "merge":
            merge_count += 1
            if step.get("from_traj"):
                merge_sources.add(step["from_traj"])
        elif t == "reasoning":
            if day:
                daily[day]["reasoning"] += 1
            cmd = step.get("cmd") or ""
            if not cmd:
                continue
            classes = classify(cmd)
            if classes:
                for c in classes:
                    class_steps[c] += 1
                    if rid:
                        class_runs[c].add(rid)
                    if day:
                        class_days[c].add(day)
                        daily[day][c] += 1
                if classes & set(RLM_CLASSES):
                    if rid:
                        rlm_runs.add(rid)
                    if "traj_read" in classes:
                        log_at_traj_read.append(bytes_so_far)
                if rid:
                    pending[rid] = classes
        elif t == "shell-output" and rid in pending:
            out_bytes = step.get("stdout_bytes")
            if not isinstance(out_bytes, (int, float)):
                out_bytes = len((step.get("stdout") or "").encode("utf-8", errors="replace"))
            for c in pending.pop(rid):
                class_out_bytes[c].append(int(out_bytes))
                if step.get("exit") not in (0, "0", None):
                    class_fail[c] += 1

classes_out = {}
for c in sorted(set(list(class_steps.keys()) + list(RLM_CLASSES))):
    classes_out[c] = {
        "steps": class_steps.get(c, 0),
        "runs": len(class_runs.get(c, ())),
        "days": len(class_days.get(c, ())),
        "out_bytes": pct(class_out_bytes.get(c, [])),
        "out_bytes_total": sum(class_out_bytes.get(c, [])),
        "failed": class_fail.get(c, 0),
    }

out = {
    "log": path,
    "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "log_lines": total,
    "parsed": parsed,
    "log_bytes": bytes_so_far,
    "first_ts": first_ts,
    "last_ts": last_ts,
    "type_counts": dict(type_counts),
    "monolith_types": dict(monolith_types),
    "runs": {"distinct_run_ids": len(run_ids), "shellm_run_steps": shellm_run_count,
             "rlm_runs": len(rlm_runs)},
    "merges": {"steps": merge_count, "distinct_sub_trajs": len(merge_sources)},
    "classes": classes_out,
    "log_bytes_at_traj_read": pct(log_at_traj_read),
    "daily": {d: dict(v) for d, v in sorted(daily.items())},
}
json.dump(out, sys.stdout, separators=(",", ":"))
