#!/usr/bin/env bash
# Leak check: run before an arm starts (adapted from the run-B script). Exits 1 on any hit, 0 when clean,
# 2 on a usage or setup error.
#
#   leak-check.sh [--kit DIR] [--identity NAME] [--run-a PATH] [--max-print N]
#                 [--mounts-report-only]
#
# --run-a is run A's archived identity dir (default
# ~/librarian-live-old/run-A-2026-10-28/app/.identities/cns), or the path of
# its librarian/store.sqlite (the identity dir is then two levels up). Run A
# is only read: the store is opened with sqlite 'mode=ro', git with
# --no-optional-locks.
#
# Scanned (everything run B's mind can reach): the whole kit app/ tree,
# identity dir included (the container mounts subdirs of app/, and the docker
# broker allows symlink targets anywhere under the app checkout), plus kit
# home/ if present. Symlinks are not followed; one that points into run A is
# a hit, one that points outside the scanned roots is a warning. Each git repo
# found is also dumped object by object (packs too), and loose git objects and
# .gz files are decompressed, so compressed copies are seen.
#
# Markers taken from run A:
#  (a) every ULID (26 chars) in its store, every node id included, and its
#      9-char queue/suggestion ids;
#  (b) sha256 of every file (64 bytes or more) under its workdir/project,
#      librarian/ and trajectories/, minus files that setup itself writes
#      (project-pristine and the project git's first commit) and the human
#      inputs (spec, charter, roles, reference/), matched by hash
#      against every run B file of the same size;
#  (c) distinctive strings: Chico, Butte, run A's project id, the 16-hex
#      input hashes in its deliverable.md and a curated list of its result
#      numbers and model names (see STRINGS below);
#  (d) its trajectory run_ids and the trajectory root id.
# Files over 50 MB that look binary are hashed but not searched for strings.
# Also prints the mounts of every running shellm-* container (docker inspect)
# for the record; a mount source inside run A is a hit (only printed with
# --mounts-report-only, for testing while run A's container still runs).
# Run it before run B's first wake: once the mind downloads public data that
# run A also downloaded, hash matches on that data are expected.
set -euo pipefail
KIT="" NAME=cns RUNA="" MAXP=20 MOUNTS_ONLY=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --kit) KIT="${2:?--kit needs a dir}"; shift 2 ;;
        --identity) NAME="${2:?--identity needs a name}"; shift 2 ;;
        --run-a) RUNA="${2:?--run-a needs a path}"; shift 2 ;;
        --max-print) MAXP="${2:?--max-print needs a number}"; shift 2 ;;
        --mounts-report-only) MOUNTS_ONLY=1; shift ;;
        -h|--help) sed -n '2,39p' "$0"; exit 0 ;;
        *) echo "leak-check.sh: unknown argument $1" >&2; exit 2 ;;
    esac
done
[[ -d "$KIT/app" ]] || { echo "leak-check.sh: no $KIT/app" >&2; exit 2; }
[[ -d "$KIT/app/.identities/$NAME" ]] || echo "warning: no identity dir $KIT/app/.identities/$NAME (setup not done?)" >&2

echo "== docker mounts of running shellm-* containers"
DOCKER_MOUNTS=""
if command -v docker >/dev/null 2>&1 && docker ps >/dev/null 2>&1; then
    names=$(docker ps --format '{{.Names}}' | grep '^shellm-' || true)
    [[ -n "$names" ]] || echo "  (none running)"
    for c in $names; do
        m=$(docker inspect --format '{{range .Mounts}}{{.Source}}	{{.Destination}}	{{.RW}}{{"\n"}}{{end}}' "$c")
        while IFS=$'\t' read -r src dst rw; do
            [[ -n "$src" ]] || continue
            printf '  %s: %s -> %s (rw=%s)\n' "$c" "$src" "$dst" "$rw"
            DOCKER_MOUNTS+="$c	$src"$'\n'
        done <<<"$m"
    done
else
    echo "  (docker not usable here; mounts not checked)"
fi
export DOCKER_MOUNTS MOUNTS_ONLY

python3 -I - "$KIT" "$NAME" "$RUNA" "$MAXP" <<'PY'
import gzip, hashlib, os, re, sqlite3, subprocess, sys, time, zlib
import traceback
# A crash is a setup error (exit 2), never a pass or a plain hit.
sys.excepthook = lambda t, v, tb: (traceback.print_exception(t, v, tb), os._exit(2))

kit, name, runa, maxp = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
t0 = time.time()
BIG = 50 * 1024 * 1024
CHUNK, OVER = 16 * 1024 * 1024, 256

def real(p): return os.path.realpath(p)
def inside(p, root): p, root = real(p), real(root); return p == root or p.startswith(root.rstrip('/') + '/')

if runa.endswith('.sqlite'):
    store = runa; runa = os.path.dirname(os.path.dirname(runa))
else:
    store = os.path.join(runa, 'librarian', 'store.sqlite')
if not os.path.isfile(store):
    # A run without memory (the control) has no store: no (a) markers then,
    # but the identity dir must exist and hold trajectories.
    if not os.path.isdir(os.path.join(runa, 'trajectories')):
        print('leak-check.sh: no run A store at %s (pass --run-a)' % store, file=sys.stderr); sys.exit(2)
    print('  warning: no store at %s: no (a) id markers (a run without memory)' % store)
    store = None
print('== run A markers from', runa)

# Curated from run A's deliverable.md (2026-10-21): result figures, model and
# file names, and place names that only run A's work would produce.
STRINGS = [
    'Pioneer Community Energy', 'B-Line', 'Chico DMV', 'charger_growth_path', 'cec_need', 'half_cec',
    'cec_t75', 'no_adas_after_2025', 'paeb_unlit_chico', 'worker_carless_refit', 'diversion_bike.json',
    'bike_penalty_check', 'fleet_from_p1', 'battery_flows.html', 'cca_chico', 'ccrs_breakdown',
    'av_rel_rate_sources', '41,454 households', '6,075 BEV', '68.22 MWh', '386 / 1100 / 2151',
    '6.33 deaths', '358 weekday-equivalent', '102.4 MW', '9f2c65bc', '0.76 deaths per 100 M',
    '12,927 to 14,938',
]
WORD_RES = [rb'(?i:chico)', rb'\bButte\b']

ULID_RE = re.compile(rb'(?<![0-9A-Za-z])[0-9A-HJKMNP-TV-Z]{26}(?![0-9A-Za-z])')
SHORT_RE = re.compile(rb'(?<![0-9A-Za-z])[A-Z][0-9A-Z]{8}(?![0-9A-Za-z])')
UUID_RE = re.compile(rb'(?<![0-9a-f])[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}(?![0-9a-f])')
HEX16_RE = re.compile(rb'(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])')

# (a) ids from the store
ulids, shorts, runids = set(), set(), set()
node_ids, pid = set(), []
if store:
    con = sqlite3.connect('file:%s?mode=ro' % store, uri=True)
    node_ids = {r[0] for r in con.execute('SELECT id FROM nodes')}
    tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'nodes_fts%'")]
    for t in tables:
        cols = [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]
        for row in con.execute('SELECT %s FROM "%s"' % (','.join('"%s"' % c for c in cols), t)):
            for v in row:
                if isinstance(v, str):
                    b = v.encode()
                    ulids.update(ULID_RE.findall(b))
        if 'run_id' in cols:
            runids.update(r[0].encode() for r in con.execute('SELECT DISTINCT run_id FROM "%s" WHERE run_id IS NOT NULL' % t))
    for t in ('checkin_queue', 'suggestions'):
        if t in tables:
            shorts.update(r[0].encode() for r in con.execute('SELECT id FROM "%s"' % t) if re.fullmatch(r'[A-Z][0-9A-Z]{8}', r[0] or ''))
    pid = (con.execute("SELECT project FROM projects").fetchall())
    con.close()
ulids.update(i.encode() for i in node_ids)
missing = [i for i in node_ids if not ULID_RE.fullmatch(i.encode())]
print('  (a) %d ULIDs (%d node ids%s), %d queue/suggestion ids' % (len(ulids), len(node_ids),
      ', %d node ids not ULID-shaped, added as literals' % len(missing) if missing else '', len(shorts)))

# (d) trajectory run ids
tdir = os.path.join(runa, 'trajectories')
lits = set(s.encode() for s in STRINGS) | set(m.encode() for m in missing)
lits.update(p[0].encode() for p in pid)
ppid = os.path.join(runa, 'project-pristine', 'project_id')
if os.path.isfile(ppid) and open(ppid).read().strip():
    lits.add(open(ppid).read().strip().encode())
pidf = os.path.join(runa, 'project-pristine', 'project_id')
if os.path.isfile(pidf): lits.add(open(pidf, 'rb').read().strip())
RUN_RE = re.compile(rb'"(?:run_id|step_id)":"([0-9a-f-]{36})"')
if os.path.isdir(tdir):
    for root in os.listdir(tdir):
        lits.add(root.encode())
        tj = os.path.join(tdir, root, 'trajectory.jsonl')
        if not os.path.isfile(tj): continue
        with open(tj, 'rb') as f:
            first = f.readline()
            m = RUN_RE.search(first)
            if m: runids.add(m.group(1))
            for line in f:
                i = line.find(b'"run_id":"')
                if i >= 0: runids.add(line[i + 10:i + 46])
runids = {r for r in runids if UUID_RE.fullmatch(r)}
print('  (d) %d run ids (trajectory and store), trajectory roots: %s' % (len(runids), ', '.join(sorted(os.listdir(tdir))) if os.path.isdir(tdir) else 'none'))

# (c) strings: curated + 16-hex input hashes from the deliverable
hex16 = set()
dl = os.path.join(runa, 'workdir', 'project', 'deliverable.md')
if os.path.isfile(dl):
    d = open(dl, 'rb').read()
    hex16 = set(HEX16_RE.findall(d))
    absent = [s for s in STRINGS if s.encode() not in d]
    print('  (c) %d curated strings (%d not in run A deliverable.md now: %s), %d input hashes, Chico, Butte, project id'
          % (len(STRINGS), len(absent), ', '.join(absent) or '-', len(hex16)))
else:
    print('  (c) %d curated strings; no deliverable.md found for input hashes' % len(STRINGS))
LIT_RE = re.compile(b'|'.join([re.escape(s) for s in sorted(lits, key=len, reverse=True)] + WORD_RES))

# (b) hashes of run A files, minus what setup writes
def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''): h.update(b)
    return h.hexdigest()

benign = set()
pp = os.path.join(runa, 'project-pristine')
for r, ds, fs in os.walk(pp):
    for f in fs: benign.add(sha(os.path.join(r, f)))
pd = os.path.join(runa, 'workdir', 'project')
if os.path.isdir(os.path.join(pd, '.git')):
    try:
        g = ['git', '--no-optional-locks', '-C', pd]
        first = subprocess.run(g + ['rev-list', '--max-parents=0', 'HEAD'], capture_output=True, text=True, check=True).stdout.split()
        for c in first:
            for line in subprocess.run(g + ['ls-tree', '-r', c], capture_output=True, text=True, check=True).stdout.splitlines():
                oid = line.split()[2]
                blob = subprocess.run(g + ['cat-file', 'blob', oid], capture_output=True, check=True).stdout
                benign.add(hashlib.sha256(blob).hexdigest())
    except (subprocess.CalledProcessError, OSError) as e:
        print('  warning: could not read run A first commit:', e)
GIT_SKIP = {'hooks', 'info', 'logs', 'refs'}
# Human inputs, not run A output: the spec, charter, roles and reference/
# (the P1 paper note, which run B receives too).
HUMAN = re.compile(r'^workdir/project/(spec\.md|charter\.md|roles/.*|reference/.*)$')
bysize, nfiles = {}, 0
for sub in ('workdir/project', 'librarian', 'trajectories'):
    top = os.path.join(runa, sub)
    for r, ds, fs in os.walk(top):
        rel = os.path.relpath(r, top).split(os.sep)
        if '.git' in rel:
            gi = rel.index('.git')
            if len(rel) == gi + 1:
                ds[:] = [x for x in ds if x not in GIT_SKIP]; fs = []   # .git top-level files are generic
        for f in fs:
            p = os.path.join(r, f)
            if os.path.islink(p) or not os.path.isfile(p): continue
            if HUMAN.match(os.path.relpath(p, runa)): continue
            sz = os.path.getsize(p)
            if sz < 64: continue
            h = sha(p)
            if h in benign: continue
            bysize.setdefault(sz, {})[h] = os.path.relpath(p, runa); nfiles += 1
print('  (b) %d run A file hashes (%d setup-written hashes excluded)' % (nfiles, len(benign)))
print('  markers built in %.1fs' % (time.time() - t0))

# scan run B
hits = []
def hit(kind, where, what):
    hits.append((kind, where, what))

def scan_bytes(data, where, seen):
    for m in ULID_RE.findall(data):
        if m in ulids and ('ulid', m) not in seen: seen.add(('ulid', m)); hit('run-A ULID', where, m.decode())
    for m in UUID_RE.findall(data):
        if m in runids and ('run', m) not in seen: seen.add(('run', m)); hit('run-A run id', where, m.decode())
    for m in SHORT_RE.findall(data):
        if m in shorts and ('short', m) not in seen: seen.add(('short', m)); hit('run-A queue id', where, m.decode())
    for m in HEX16_RE.findall(data):
        if m in hex16 and ('hex', m) not in seen: seen.add(('hex', m)); hit('run-A input hash', where, m.decode())
    for m in LIT_RE.finditer(data):
        s = m.group(0)
        if ('lit', s) not in seen: seen.add(('lit', s)); hit('run-A string', where, s.decode('utf-8', 'replace'))

def scan_stream(f, where):
    seen, tail = set(), b''
    while True:
        b = f.read(CHUNK)
        if not b: break
        scan_bytes(tail + b, where, seen); tail = b[-OVER:]

roots = [os.path.join(kit, 'app')] + ([os.path.join(kit, 'home')] if os.path.isdir(os.path.join(kit, 'home')) else [])
if any(inside(runa, r) for r in roots):
    hit('run A inside scanned tree', runa, 'run A identity dir is under %s (not moved out?)' % kit)
warns, nscan, nbytes, gitdirs = [], 0, 0, []
for root in roots:
    for r, ds, fs in os.walk(root):
        keep = []
        for dname in ds:
            p = os.path.join(r, dname)
            if os.path.islink(p): fs.append(dname); continue
            if inside(p, runa): continue
            if dname == '.git' and os.path.isdir(os.path.join(p, 'objects')): gitdirs.append(p)
            keep.append(dname)
        ds[:] = keep
        for f in fs:
            p = os.path.join(r, f)
            rel = os.path.relpath(p, kit)
            scan_bytes(rel.encode(), 'path ' + rel, set())
            if os.path.islink(p):
                t = real(p)
                if inside(t, runa): hit('symlink into run A', rel, t)
                elif not any(inside(t, x) for x in roots): warns.append('symlink leaves the scanned roots: %s -> %s' % (rel, t))
                continue
            if not os.path.isfile(p): continue
            try:
                sz = os.path.getsize(p)
                if sz in bysize:
                    h = sha(p)
                    if h in bysize[sz]: hit('run-A file (sha256)', rel, bysize[sz][h])
                with open(p, 'rb') as fh:
                    head = fh.read(8192)
                    if sz > BIG and b'\0' in head: continue
                    fh.seek(0)
                    if re.search(r'/\.git/objects/[0-9a-f]{2}/[0-9a-f]{38}$', p):
                        scan_bytes(zlib.decompress(fh.read()), rel + ' (inflated)', set())
                    elif p.endswith('.gz') and sz <= BIG:
                        with gzip.open(p, 'rb') as gz: scan_stream(gz, rel + ' (gunzip)')
                    else:
                        scan_stream(fh, rel)
                nscan += 1; nbytes += sz
            except (OSError, zlib.error, EOFError) as e:
                warns.append('could not read %s: %s' % (rel, e))
for g in gitdirs:
    try:
        pr = subprocess.Popen(['git', '--no-optional-locks', '--git-dir', g, 'cat-file', '--batch-all-objects', '--batch'],
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        scan_stream(pr.stdout, os.path.relpath(g, kit) + ' (all objects)'); pr.wait()
    except OSError as e:
        warns.append('git dump failed for %s: %s' % (g, e))

# Only this kit's containers (those mounting something under the kit app/) are
# reachable by its mind; another kit's container is noted once, not counted.
mounts = {}
for line in os.environ.get('DOCKER_MOUNTS', '').splitlines():
    c, _, src = line.partition('\t')
    if src: mounts.setdefault(c, []).append(src)
for c, srcs in sorted(mounts.items()):
    if not any(inside(src, os.path.join(kit, 'app')) for src in srcs):
        warns.append('container %s belongs to another kit (no mount under %s/app); not counted' % (c, kit)); continue
    for src in srcs:
        if inside(src, runa):
            if os.environ.get('MOUNTS_ONLY') == '1': warns.append('container %s mounts %s, inside run A (not counted: --mounts-report-only)' % (c, src))
            else: hit('container mount into run A', c, src)
        elif not inside(src, os.path.join(kit, 'app')): warns.append('container %s mounts %s, outside the kit app/' % (c, src))

print('== scanned %d files (%.1f MB) and %d git repos under %s in %.1fs' % (nscan, nbytes / 1e6, len(gitdirs), ', '.join(roots), time.time() - t0))
for w in warns[:maxp]: print('  warning:', w)
if len(warns) > maxp: print('  ... %d more warnings' % (len(warns) - maxp))
if not hits:
    print('== LEAK CHECK PASSED: 0 hits'); sys.exit(0)
kinds = {}
for k, w, x in hits: kinds[k] = kinds.get(k, 0) + 1
print('== LEAK CHECK FAILED: %d hits (%s)' % (len(hits), ', '.join('%s %d' % kv for kv in sorted(kinds.items()))))
for k, w, x in hits[:maxp]: print('  HIT %s: %s: %s' % (k, w, x))
if len(hits) > maxp: print('  ... %d more' % (len(hits) - maxp))
sys.exit(1)
PY
