#!/usr/bin/env python3
"""Render the audel-metrics JSON cache as a self-contained HTML chart page.

Usage: audel-metrics-render.py <metrics.json> <out.html>

The page shows daily usage (tokens, messages, model calls and runs per UTC
day, stacked/grouped bars, plus a per-model token table) and the reply-latency
baseline: a KPI row, then two ECDF panels ("share of replies delivered within
X") on a log time axis — split by reply path (fast vs in-run) and by arrival
condition (idle vs during a run). Stamped reply pairs only, same definition
as the text report.
"""
import json
import math
import sys


def pct_at(vs, p):
    return vs[int(round(p / 100.0 * (len(vs) - 1)))]


def fmt_dur(s):
    if s < 90:
        return "%ds" % round(s)
    if s < 5400:
        return "%dm" % round(s / 60)
    if s < 129600:
        return ("%.1fh" % (s / 3600)).replace(".0h", "h")
    return ("%.1fd" % (s / 86400)).replace(".0d", "d")


def fmt_num(n):
    n = float(n)
    if n >= 1e9:
        return ("%.1fB" % (n / 1e9)).replace(".0B", "B")
    if n >= 1e6:
        return ("%.1fM" % (n / 1e6)).replace(".0M", "M")
    if n >= 1e3:
        return ("%.1fk" % (n / 1e3)).replace(".0k", "k")
    return "%d" % n


def nice_max(v):
    """Round a y-axis max up to 1/2/2.5/5 x 10^k."""
    if v <= 0:
        return 1
    mag = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * mag:
            return m * mag
    return 10 * mag


BAR_PANELS = []   # JS hover data for every bar panel rendered


def bar_panel(pid, days, series, stacked, total_label=None):
    """Per-day bars. series: list of (key, label, css_class); values come
    from each day's counter dict. stacked=True stacks the series, else
    groups them side by side. total_label adds a summed line to the hover
    tooltip (omit when summing the series makes no sense)."""
    W, H, ML, MR, MT, MB = 640, 240, 50, 12, 12, 28
    PW, PH = W - ML - MR, H - MT - MB
    n = max(1, len(days))
    if stacked:
        ymax = max([sum(v.get(k, 0) for k, _, _ in series) for _, v in days] or [0])
    else:
        ymax = max([v.get(k, 0) for _, v in days for k, _, _ in series] or [0])
    ymax = nice_max(ymax)
    slot = PW / n
    parts = []
    for f in (0.25, 0.5, 0.75, 1.0):
        y = MT + (1 - f) * PH
        parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>' % (ML, y, W - MR, y))
        parts.append('<text x="%.1f" y="%.1f" class="tick" text-anchor="end">%s</text>'
                     % (ML - 6, y + 4, fmt_num(ymax * f)))
    parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="axis"/>' % (ML, H - MB, W - MR, H - MB))
    label_every = max(1, int(math.ceil(n / 9.0)))
    for i, (day, v) in enumerate(days):
        x0 = ML + i * slot
        if i % label_every == 0 or (i == n - 1 and i % label_every >= 2):
            parts.append('<text x="%.1f" y="%.1f" class="tick" text-anchor="middle">%s</text>'
                         % (x0 + slot / 2, H - MB + 15, day[5:]))
        if stacked:
            acc = 0
            bw = max(1.0, slot * 0.7)
            for k, lbl, cls in series:
                val = v.get(k, 0)
                if val <= 0:
                    continue
                h = val / ymax * PH
                y = MT + PH - (acc + val) / ymax * PH
                parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="bar %s"/>'
                             % (x0 + (slot - bw) / 2, y, bw, h, cls))
                acc += val
        else:
            m = len(series)
            bw = max(1.0, slot * 0.8 / m)
            for j, (k, lbl, cls) in enumerate(series):
                val = v.get(k, 0)
                if val <= 0:
                    continue
                h = val / ymax * PH
                parts.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" class="bar %s"/>'
                             % (x0 + slot * 0.1 + j * bw, MT + PH - h, bw, h, cls))
    legend = '<div class="legend">' + "".join(
        '<span><i class="chip %s"></i>%s</span>' % (cls, lbl) for _, lbl, cls in series) + "</div>"
    BAR_PANELS.append({
        "id": pid, "W": W, "ML": ML, "PW": PW, "MT": MT, "PH": PH,
        "days": [d for d, _ in days],
        "series": [[lbl, cls, [int(v.get(k, 0)) for _, v in days]] for k, lbl, cls in series],
        "total": total_label,
    })
    return ('%s<div class="panelwrap"><svg id="%s" viewBox="0 0 %d %d">%s'
            '<rect class="hl" x="0" y="%d" width="0" height="%d" visibility="hidden"/></svg>'
            '<div class="tip" hidden></div></div>' % (legend, pid, W, H, "".join(parts), MT, PH))


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip())
    data = json.load(open(sys.argv[1]))
    recs = data["records"]

    paired = [r for r in recs if r[0] is not None and r[4] == "stamped"]
    series = {
        "fast": sorted(round(r[0], 1) for r in paired if r[1] == "fast"),
        "in_run": sorted(round(r[0], 1) for r in paired if r[1] == "in_run"),
        "idle": sorted(round(r[0], 1) for r in paired if not r[2]),
        "busy": sorted(round(r[0], 1) for r in paired if r[2]),
    }
    all_lats = sorted(r[0] for r in paired)
    if not all_lats:
        sys.exit("no stamped reply pairs in the data")
    busy_share = round(100.0 * sum(1 for r in recs if r[2]) / max(1, len(recs)))

    # Log-x domain, padded to the tick above the max latency.
    ticks = [(1, "1s"), (10, "10s"), (60, "1m"), (600, "10m"),
             (3600, "1h"), (21600, "6h"), (86400, "1d"), (345600, "4d")]
    xmax = next(v for v, _ in ticks if v >= all_lats[-1]) if all_lats[-1] <= ticks[-1][0] else all_lats[-1]
    xmin = 1.0
    ticks = [(v, l) for v, l in ticks if xmin <= v <= xmax]

    W, H, ML, MR, MT, MB = 640, 300, 46, 16, 10, 30
    PW, PH = W - ML - MR, H - MT - MB
    span = math.log10(xmax) - math.log10(xmin)

    def xs(v):
        return ML + (math.log10(max(v, xmin)) - math.log10(xmin)) / span * PW

    def ys(frac):
        return MT + (1.0 - frac) * PH

    def ecdf_path(vs):
        d = ["M %.1f %.1f" % (xs(vs[0]), ys(0))]
        for i, v in enumerate(vs):
            d.append("H %.1f" % xs(v))
            d.append("V %.1f" % ys((i + 1) / len(vs)))
        d.append("H %.1f" % xs(xmax))
        return " ".join(d)

    grid = "".join(
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>' % (ML, ys(f), W - MR, ys(f))
        for f in (0.25, 0.5, 0.75, 1.0))
    xaxis = "".join(
        '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="grid"/>'
        '<text x="%.1f" y="%.1f" class="tick" text-anchor="middle">%s</text>'
        % (xs(v), MT, xs(v), H - MB, xs(v), H - MB + 16, l) for v, l in ticks)
    yaxis = "".join(
        '<text x="%.1f" y="%.1f" class="tick" text-anchor="end">%d%%</text>'
        % (ML - 8, ys(f) + 4, int(f * 100)) for f in (0, 0.25, 0.5, 0.75, 1.0))
    ref = ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="ref"/>'
           '<text x="%.1f" y="%.1f" class="tick" text-anchor="middle">2m: expected typical after the fix</text>'
           % (xs(120), MT, xs(120), H - MB, xs(120), MT + 10))

    def panel(pid, s1_key, s1_label, s2_key, s2_label):
        parts = [grid, xaxis, yaxis,
                 '<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" class="axis"/>' % (ML, H - MB, W - MR, H - MB),
                 ref]
        for key, label, cls, anchor, dx, dy in (
                (s1_key, s1_label, "s1", "end", -10, -8),
                (s2_key, s2_label, "s2", "start", 10, 18)):
            vs = series[key]
            if not vs:
                continue
            parts.append('<path d="%s" class="line %s"/>' % (ecdf_path(vs), cls))
            lx,ly = xs(pct_at(vs, 50)), ys(0.5)
            parts.append('<circle cx="%.1f" cy="%.1f" r="4" class="chip %s"/>'
                         '<text x="%.1f" y="%.1f" class="dlabel" text-anchor="%s">%s</text>'
                         % (lx + (dx // 2), ly + dy - 4, cls, lx + dx, ly + dy, anchor, label))
        legend = ('<div class="legend">'
                  '<span><i class="chip s1"></i>%s</span><span><i class="chip s2"></i>%s</span></div>'
                  % (s1_label, s2_label))
        return ('%s<div class="panelwrap"><svg id="%s" viewBox="0 0 %d %d">%s'
                '<rect class="overlay" x="%d" y="%d" width="%d" height="%d"/>'
                '<line class="xhair" y1="%d" y2="%d" visibility="hidden"/></svg>'
                '<div class="tip" hidden></div></div>' % (legend, pid, W, H, "".join(parts), ML, MT, PW, PH, MT, H - MB))

    def stat_row(label, vs):
        return ("<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
                % (label, len(vs), fmt_dur(pct_at(vs, 50)), fmt_dur(pct_at(vs, 90)),
                   fmt_dur(pct_at(vs, 95)), fmt_dur(vs[-1]))) if vs else ""

    table = "".join(stat_row(l, series[k]) for l, k in (
        ("fast path", "fast"), ("in-run reply", "in_run"),
        ("arrived while idle", "idle"), ("arrived during a run", "busy")))

    days = data.get("daily") or []
    last7 = [v for _, v in days[-7:]]
    tot_tok = sum(v["in"] + v["out"] + v["think"] for _, v in days)
    tok7 = sum(v["in"] + v["out"] + v["think"] for v in last7) / max(1, len(last7))
    msg7 = sum(v["in_msg"] + v["out_msg"] for v in last7) / max(1, len(last7))
    calls7 = sum(v["calls"] for v in last7) / max(1, len(last7))
    usage_tiles = "".join('<div class="tile"><div class="v">%s</div><div class="l">%s</div></div>' % t for t in (
        (fmt_num(tot_tok), "tokens, all time"),
        (fmt_num(tok7), "tokens / day, last 7d"),
        ("%.0f" % msg7, "messages / day, last 7d"),
        ("%.0f" % calls7, "model calls / day, last 7d"),
        (str(len(days)), "days in the log")))
    tiles = "".join('<div class="tile"><div class="v">%s</div><div class="l">%s</div></div>' % t for t in (
        (str(data["inbound"]), "inbound messages"),
        ("%d%%" % busy_share, "arrive during a run"),
        (fmt_dur(pct_at(all_lats, 50)), "median reply"),
        (fmt_dur(pct_at(all_lats, 95)), "p95 reply")))
    tok_panel = bar_panel("d1", days, [("in", "input", "s1"), ("out", "output", "s2"), ("think", "thinking", "s3")], True, "total tokens")
    msg_panel = bar_panel("d2", days, [("in_msg", "inbound", "s1"), ("out_msg", "outbound", "s2")], False, "total messages")
    act_panel = bar_panel("d3", days, [("calls", "model calls", "s1"), ("runs", "runs started", "s2"), ("reasoning", "reasoning steps", "s3")], False)
    bym = data.get("by_model") or {}
    model_rows = "".join(
        "<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>"
        % (m, v["calls"], "{:,}".format(v["in"]), "{:,}".format(v["out"]), "{:,}".format(v["think"]))
        for m, v in sorted(bym.items(), key=lambda kv: -kv[1]["in"]) if v["calls"] > 0)
    model_table = ('<table><tr><th>model</th><th>calls</th><th>input</th><th>output</th><th>thinking</th></tr>%s</table>'
                   % model_rows) if model_rows else "<p class=\"note\">no usage stamped yet</p>"
    # What the calls/tokens cover: the llm ledger (every bin/llm call) on the
    # days it has rows, shellm-run stamps (reasoning steps) before that.
    ledger_since = (data.get("ledger") or {}).get("since")
    if not ledger_since:
        coverage = ("shellm runs only (tokens bin/shellm stamps on reasoning steps); the llm usage ledger "
                    "has no calls yet, so fast-path replies and other thinkers are missing.")
    elif days and ledger_since == days[0][0]:
        coverage = "every bin/llm call (usage ledger): shellm runs, fast-path replies and other thinkers."
    else:
        coverage = ("from %s on, every bin/llm call (usage ledger); before that shellm runs only (tokens "
                    "stamped on reasoning steps), so fast-path replies and other thinkers are missing on those days."
                    % ledger_since)

    html = HTML_TEMPLATE
    for token, value in (
            ("@@TITLE@@", "%s usage and reply latency" % data["identity"].capitalize()),
            ("@@GENERATED@@", data["generated"]),
            ("@@USAGE_TILES@@", usage_tiles),
            ("@@TOK_PANEL@@", tok_panel),
            ("@@MSG_PANEL@@", msg_panel),
            ("@@ACT_PANEL@@", act_panel),
            ("@@MODEL_TABLE@@", model_table),
            ("@@COVERAGE@@", coverage),
            ("@@TILES@@", tiles),
            ("@@PANEL1@@", panel("p1", "fast", "fast path", "in_run", "in-run reply")),
            ("@@PANEL2@@", panel("p2", "idle", "arrived while idle", "busy", "arrived during a run")),
            ("@@TABLE@@", table),
            ("@@DATA@@", json.dumps({"series": series, "xmin": xmin, "xmax": xmax,
                                     "W": W, "ML": ML, "MR": MR, "bars": BAR_PANELS}, separators=(",", ":"))),
    ):
        html = html.replace(token, value)
    with open(sys.argv[2], "w") as fh:
        fh.write(html)
    print("wrote", sys.argv[2])


HTML_TEMPLATE = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>@@TITLE@@</title>
<style>
.viz-root {
  color-scheme: light;
  --surface-1: #fcfcfb; --page: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #8a8f98;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .viz-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --page: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --series-1: #3987e5; --series-2: #d95926; --series-3: #7d828b;
  }
}
:root[data-theme="dark"] .viz-root {
  color-scheme: dark;
  --surface-1: #1a1a19; --page: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --series-1: #3987e5; --series-2: #d95926; --series-3: #7d828b;
}
html, body { margin: 0; }
.viz-root { background: var(--page); color: var(--ink-1); min-height: 100vh; padding: 24px;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif; box-sizing: border-box; }
.wrap { max-width: 1100px; margin: 0 auto; }
h1 { font-size: 19px; margin: 0 0 2px; }
.sub { color: var(--ink-2); font-size: 13px; margin: 0 0 18px; }
.tiles { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 18px; }
.tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 18px; min-width: 128px; }
.tile .v { font-size: 30px; }
.tile .l { color: var(--ink-2); font-size: 12px; margin-top: 2px; }
.charts { display: flex; flex-wrap: wrap; gap: 16px; }
.card { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
  padding: 14px 14px 8px; flex: 1 1 460px; min-width: 0; }
.card h2 { font-size: 14px; margin: 0 0 2px; }
.card .note { color: var(--ink-2); font-size: 12px; margin: 0 0 8px; }
.legend { display: flex; gap: 16px; font-size: 12px; color: var(--ink-2); margin: 0 0 4px; }
.legend span { display: inline-flex; align-items: center; gap: 6px; }
i.chip { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
svg { width: 100%; height: auto; display: block; }
.grid { stroke: var(--grid); stroke-width: 1; }
.axis { stroke: var(--axis); stroke-width: 1; }
.tick { fill: var(--muted); font-size: 11px; }
.dlabel { fill: var(--ink-2); font-size: 12px; }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; }
.line.s1 { stroke: var(--series-1); } circle.chip.s1 { fill: var(--series-1); } i.chip.s1 { background: var(--series-1); }
.line.s2 { stroke: var(--series-2); } circle.chip.s2 { fill: var(--series-2); } i.chip.s2 { background: var(--series-2); }
i.chip.s3 { background: var(--series-3); }
.bar.s1 { fill: var(--series-1); } .bar.s2 { fill: var(--series-2); } .bar.s3 { fill: var(--series-3); }
.hl { fill: var(--ink-1); opacity: 0.06; pointer-events: none; }
h1.section { font-size: 16px; margin: 26px 0 2px; }
circle.chip { stroke-width: 2; stroke: var(--surface-1); }
.ref { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 4 4; }
.overlay { fill: transparent; }
.xhair { stroke: var(--muted); stroke-width: 1; }
.panelwrap { position: relative; }
.tip { position: absolute; pointer-events: none; background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 6px; padding: 6px 9px; font-size: 12px;
  color: var(--ink-2); box-shadow: 0 2px 8px rgba(0,0,0,0.12); white-space: nowrap; }
.tip b { color: var(--ink-1); }
details { margin-top: 16px; color: var(--ink-2); font-size: 13px; }
table { border-collapse: collapse; margin-top: 8px; font-size: 13px; }
td, th { padding: 4px 12px 4px 0; text-align: right; font-variant-numeric: tabular-nums; }
td:first-child, th:first-child { text-align: left; }
th { color: var(--muted); font-weight: 500; }
</style></head>
<body><div class="viz-root"><div class="wrap">
<h1>@@TITLE@@</h1>
<p class="sub">From the full mind log, pulled @@GENERATED@@. Days are UTC.</p>
<div class="tiles">@@USAGE_TILES@@</div>
<div class="charts">
<div class="card"><h2>Tokens per day</h2>
<p class="note">Input, output and thinking tokens. Coverage: @@COVERAGE@@ Hover a bar for the numbers.</p>
@@TOK_PANEL@@</div>
<div class="card"><h2>Messages per day</h2>
<p class="note">Inbound = messages to the identity from anyone else; outbound = its own messages out.</p>
@@MSG_PANEL@@</div>
<div class="card"><h2>Activity per day</h2>
<p class="note">Model calls (same coverage as the tokens chart), agentic runs started, and reasoning steps.</p>
@@ACT_PANEL@@</div>
<div class="card"><h2>Tokens per model</h2>
<p class="note">Same coverage as the tokens chart. Ledger days carry the model on each call; on mind-log days
it comes from the run's shellm-run row ("?" = steps with no run id).</p>
@@MODEL_TABLE@@</div>
</div>
<h1 class="section">Reply latency</h1>
<p class="sub">Share of replies delivered within a given time. Stamped reply pairs only. Log time axis.</p>
<div class="tiles">@@TILES@@</div>
<div class="charts">
<div class="card"><h2>By reply path</h2>
<p class="note">The fast path replies with one LLM call; in-run replies come from inside an agentic run.</p>
@@PANEL1@@</div>
<div class="card"><h2>By arrival condition</h2>
<p class="note">Whether a run was in progress when the message arrived.</p>
@@PANEL2@@</div>
</div>
<details><summary>Data table (seconds, formatted)</summary>
<table><tr><th>segment</th><th>n</th><th>p50</th><th>p90</th><th>p95</th><th>max</th></tr>@@TABLE@@</table>
</details>
<script>
const D = @@DATA@@;
const PANELS = [
  ["p1", [["fast path", D.series.fast], ["in-run reply", D.series.in_run]]],
  ["p2", [["arrived while idle", D.series.idle], ["arrived during a run", D.series.busy]]],
];
const lg = Math.log10, span = lg(D.xmax) - lg(D.xmin), PW = D.W - D.ML - D.MR;
function fmtDur(s) {
  if (s < 90) return Math.round(s) + "s";
  if (s < 5400) return Math.round(s / 60) + "m";
  if (s < 129600) return (s / 3600).toFixed(1).replace(/\\.0$/, "") + "h";
  return (s / 86400).toFixed(1).replace(/\\.0$/, "") + "d";
}
function fracLE(sorted, v) {
  let lo = 0, hi = sorted.length;
  while (lo < hi) { const m = (lo + hi) >> 1; if (sorted[m] <= v) lo = m + 1; else hi = m; }
  return lo / sorted.length;
}
for (const p of D.bars) {
  const svg = document.getElementById(p.id);
  const wrapEl = svg.parentElement, tip = wrapEl.querySelector(".tip"), hl = svg.querySelector(".hl");
  const slot = p.PW / Math.max(1, p.days.length);
  svg.addEventListener("mousemove", (ev) => {
    const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());
    const i = Math.floor((pt.x - p.ML) / slot);
    if (pt.x < p.ML || i < 0 || i >= p.days.length) { tip.hidden = true; hl.setAttribute("visibility", "hidden"); return; }
    hl.setAttribute("x", p.ML + i * slot); hl.setAttribute("width", slot); hl.setAttribute("visibility", "visible");
    let rows = p.series.map(([name, cls, vs]) => name + ": <b>" + vs[i].toLocaleString() + "</b>");
    if (p.total) rows.push(p.total + ": <b>" + p.series.reduce((a, s) => a + s[2][i], 0).toLocaleString() + "</b>");
    tip.innerHTML = "<b>" + p.days[i] + "</b><br>" + rows.join("<br>");
    tip.hidden = false;
    const r = wrapEl.getBoundingClientRect(), sr = svg.getBoundingClientRect();
    let left = sr.left - r.left + (pt.x / p.W) * sr.width + 14;
    if (left + tip.offsetWidth > r.width - 4) left -= tip.offsetWidth + 28;
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, ev.clientY - r.top - tip.offsetHeight - 10) + "px";
  });
  svg.addEventListener("mouseleave", () => { tip.hidden = true; hl.setAttribute("visibility", "hidden"); });
}
for (const [pid, ss] of PANELS) {
  const svg = document.getElementById(pid);
  const wrapEl = svg.parentElement, tip = wrapEl.querySelector(".tip"),
        xhair = svg.querySelector(".xhair");
  svg.addEventListener("mousemove", (ev) => {
    const pt = new DOMPoint(ev.clientX, ev.clientY).matrixTransform(svg.getScreenCTM().inverse());
    if (pt.x < D.ML || pt.x > D.ML + PW) { tip.hidden = true; xhair.setAttribute("visibility", "hidden"); return; }
    const v = Math.pow(10, lg(D.xmin) + (pt.x - D.ML) / PW * span);
    xhair.setAttribute("x1", pt.x); xhair.setAttribute("x2", pt.x);
    xhair.setAttribute("visibility", "visible");
    tip.innerHTML = "<b>within " + fmtDur(v) + "</b><br>" +
      ss.map(([name, vs]) => name + ": <b>" + Math.round(100 * fracLE(vs, v)) + "%</b>").join("<br>");
    tip.hidden = false;
    const r = wrapEl.getBoundingClientRect(), sr = svg.getBoundingClientRect();
    let left = sr.left - r.left + (pt.x / D.W) * sr.width + 14;
    if (left + tip.offsetWidth > r.width - 4) left -= tip.offsetWidth + 28;
    tip.style.left = left + "px";
    tip.style.top = Math.max(0, ev.clientY - r.top - tip.offsetHeight - 10) + "px";
  });
  svg.addEventListener("mouseleave", () => { tip.hidden = true; xhair.setAttribute("visibility", "hidden"); });
}
</script>
</div></div></body></html>
"""

if __name__ == "__main__":
    main()
