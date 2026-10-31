#!/usr/bin/env python3
"""Health check and smoke-trial pass criteria for trial v2 kits.

    python3 trials/v2/check.py ~/kit-a ~/kit-b [--json]

Read-only. For each kit: arm, briefs started, mind running, last model call,
spend, wakes, project commits, archived projects; for the memory arm the store
(nodes by type, packs, shared facts and conflicts, facts from verdicts, lessons
judged, citations) and for the control arm that no store exists and no
librarian line reached a prompt. Exit 1 when a pass criterion fails.
"""
import glob
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

ULID = re.compile(r"\b[0-9A-HJKMNP-TV-Z]{26}\b")


def read(p, default=""):
    try:
        with open(p, errors="replace") as f:
            return f.read()
    except OSError:
        return default


def pgrep(pattern):
    out = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True).stdout.split()
    return [int(x) for x in out if x.isdigit()]


def ledger(path):
    rows = []
    for line in read(path).splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def check_kit(kit):
    r = {"kit": kit, "fail": []}
    ident = f"{kit}/app/.identities/cns"
    r["arm"] = read(f"{kit}/trial/ARM").strip() or "?"
    r["scale"] = read(f"{kit}/trial/scale").strip()
    start = read(f"{kit}/trial/started_at").strip()
    r["started_at"] = start
    r["briefs_started"] = [ln.split()[0] for ln in read(f"{kit}/trial/applied").splitlines() if ln.strip()]
    r["mind_running"] = bool(pgrep(f"{kit}/app/bin/thinkers start"))
    r["scheduler_running"] = bool(pgrep(f"scheduler.sh --kit {kit}"))
    r["end_at_running"] = bool(pgrep(f"end-at.sh --kit {kit}"))
    led = ledger(f"{ident}/usage/llm.jsonl")
    r["calls"] = len(led)
    r["spend_usd"] = round(sum(float(x.get("cost_usd") or 0) for x in led), 2)
    wakes = {x.get("run_id") for x in led if x.get("run_id") and not str(x.get("run_id")).startswith("librarian")}
    r["runs"] = len(wakes)
    r["usd_per_run"] = round(r["spend_usd"] / len(wakes), 3) if wakes else None
    r["last_call"] = led[-1]["ts"] if led else None
    if led:
        age = time.time() - time.mktime(time.strptime(led[-1]["ts"], "%Y-%m-%dT%H:%M:%SZ")) + time.timezone
        r["minutes_since_last_call"] = round(age / 60, 1)
    pd = f"{ident}/workdir/project"
    if os.path.isdir(f"{pd}/.git"):
        r["project_commits"] = int(subprocess.run(["git", "-C", pd, "rev-list", "--count", "HEAD"], capture_output=True, text=True).stdout.strip() or 0)
        r["project_id"] = read(f"{ident}/project-pristine/project_id").strip()
        r["deliverable_bytes"] = os.path.getsize(f"{pd}/deliverable.md") if os.path.exists(f"{pd}/deliverable.md") else 0
        r["reviews"] = len(glob.glob(f"{pd}/reviews/**/*.md", recursive=True))
    r["archived_projects"] = sorted(os.path.basename(p) for p in glob.glob(f"{kit}/archive/*"))
    r["old_project_in_workdir"] = sorted(os.path.basename(p) for p in glob.glob(f"{ident}/workdir/project.old-*"))
    if r["old_project_in_workdir"]:
        r["fail"].append("an old project is still inside workdir (reachable by the mind)")
    # Prompts: did any librarian text reach the control arm?
    traj = " ".join(read(p) for p in glob.glob(f"{ident}/trajectories/*/trajectory.jsonl")[:3])
    store = f"{ident}/librarian/store.sqlite"
    if r["arm"] == "control":
        if os.path.exists(store):
            r["fail"].append("control arm has a store")
        if "[TASK MEMORIES]" in traj or "LESSON DUE" in traj or "librarian propose" in traj:
            r["fail"].append("librarian text reached a control-arm prompt")
    elif os.path.exists(store):
        c = sqlite3.connect(f"file:{store}?mode=ro", uri=True)
        q = lambda s, a=(): c.execute(s, a).fetchall()  # noqa: E731
        r["store"] = {
            "nodes": dict(q("select type, count(*) from nodes where status in ('active','probationary') group by 1")),
            "packs": q("select count(*) from requests where kind='pack'")[0][0],
            "pack_tokens_avg": q("select round(avg(used_tokens)) from requests where kind='pack'")[0][0],
            "projects_seen": q("select count(distinct project) from requests where kind='pack'")[0][0],
            "shared_facts": q("select count(*) from nodes n where type='fact' and status in ('active','probationary') and exists (select 1 from tags t where t.node_id=n.id and t.tag like 'shared:%')")[0][0],
            "facts_from_verdicts": q("select count(*) from nodes where type='fact' and json_extract(provenance,'$.method')='review'")[0][0],
            "review_claims": dict(q("select verdict, count(*) from review_claim group by 1")),
            "lessons_judged": dict(q("select outcome, count(*) from lesson_judged group by 1")),
            "pending_lesson": q("select kind, count(*) from pending_lesson group by 1"),
            "cites": q("select count(*) from citations where source='cite'")[0][0],
            "lesson_rows_shown": q("select count(*) from retrieval_log where section='lesson'")[0][0],
            "shared_rows_shown": q("select count(*) from retrieval_log where section='shared'")[0][0],
            "task_rows_shown": q("select count(*) from retrieval_log where section='task'")[0][0],
            "searches": q("select count(*) from requests where kind='search'")[0][0],
            "episodes_in_packs": q("select count(*) from retrieval_log rl join nodes n on n.id=rl.node_id where rl.source='pack' and n.type='episode'")[0][0],
        }
        if r["store"]["episodes_in_packs"]:
            r["fail"].append("episodes reached a pack")
        if len(r["briefs_started"]) >= 2 and r["store"]["projects_seen"] < 2:
            r["fail"].append("store did not see the second brief's project")
        if len(r["briefs_started"]) >= 2 and not os.path.exists(f"{pd}/shared-values.md"):
            r["fail"].append("new project has no shared-values.md")
    else:
        r["fail"].append("memory arm has no store")
    err = read(f"{ident}/run/librarian.log")
    r["librarian_log_lines"] = len(err.splitlines())
    if "Traceback" in err:
        r["fail"].append("traceback in librarian.log")
    if "No space left" in read(f"{ident}/run/logs/monolith.log")[-200000:]:
        r["fail"].append("disk full in monolith.log")
    return r


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    as_json = "--json" in sys.argv
    if not args:
        print(__doc__)
        return 2
    rc = 0
    for kit in args:
        kit = os.path.abspath(os.path.expanduser(kit))
        r = check_kit(kit)
        if r["fail"]:
            rc = 1
        if as_json:
            print(json.dumps(r, indent=2, default=str))
        else:
            print(f"== {kit} ({r['arm']}, scale {r['scale']}) briefs {r['briefs_started']} mind {'up' if r['mind_running'] else 'DOWN'} scheduler {'up' if r['scheduler_running'] else 'down'} end-at {'up' if r['end_at_running'] else 'down'}")
            print(f"   runs {r['runs']}, calls {r['calls']}, ${r['spend_usd']} (${r['usd_per_run']} per run), last call {r['last_call']} ({r.get('minutes_since_last_call')} min ago)")
            print(f"   project {r.get('project_id')}: commits {r.get('project_commits')}, deliverable {r.get('deliverable_bytes')} bytes, reviews {r.get('reviews')}; archived {r['archived_projects']}")
            if "store" in r:
                print("   store: " + json.dumps(r["store"], default=str))
            print("   FAIL: " + "; ".join(r["fail"]) if r["fail"] else "   pass")
    return rc


if __name__ == "__main__":
    sys.exit(main())
