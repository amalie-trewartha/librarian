#!/usr/bin/env python3
"""Render the Audel usage report from pulled per-day message counts.

Usage: audel-usage-render.py <data.json> <out.html>

Input is the JSON cached by deploy/scripts/audel-usage: rows of
[utc_day, channel, user, inbound, outbound] plus a user->display-name map.
Output is a self-contained HTML file (no external assets): a KPI row,
weekly and daily stacked columns for messages-by-channel and new/returning
users (daily stops at the last complete UTC day), table views for every
chart, and a per-user table. Stdlib only.
"""

import html
import json
import sys
from datetime import date, timedelta

CHANNELS = [
    ("slack", "Slack"),
    ("telegram", "Telegram"),
    ("pwa", "Chat PWA"),
    ("other", "Other"),
]
# Categorical slots in fixed order (see design/dataviz palette): slot N is
# --sN in the page CSS; channels take slots by canonical order above, and
# the users chart takes slots 1 (returning) and 2 (new).
SLOT_VARS = ["--s1", "--s2", "--s3", "--s4"]


def week_of(day_str):
    d = date.fromisoformat(day_str)
    return (d - timedelta(days=d.weekday())).isoformat()


def week_label(week_key, with_year):
    d = date.fromisoformat(week_key)
    base = f"{d.strftime('%b')} {d.day}"
    return f"{base} '{d.strftime('%y')}" if with_year else base


def compact(n):
    if n >= 10_000_000:
        return f"{n / 1_000_000:.0f}M"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 10_000:
        return f"{n / 1000:.1f}K"
    return f"{n:,}"


def build(data):
    rows = data.get("rows", [])
    names = data.get("names", {})

    if not rows:
        return None

    # Per-user rollup. "Active" means the user sent something (inbound side);
    # outbound-only rows still show up in weekly reply totals.
    users = {}
    for day, chan, user, n_in, n_out in rows:
        u = users.setdefault(
            user,
            {"chan": chan, "in": 0, "out": 0, "days": set(), "first": day, "last": day},
        )
        u["in"] += n_in
        u["out"] += n_out
        if n_in:
            u["days"].add(day)
            u["first"] = min(u["first"], day)
            u["last"] = max(u["last"], day)

    # Continuous week range over the data.
    first_wk = date.fromisoformat(week_of(min(r[0] for r in rows)))
    last_wk = date.fromisoformat(week_of(max(r[0] for r in rows)))
    weeks = []
    w = first_wk
    while w <= last_wk:
        weeks.append(w.isoformat())
        w += timedelta(days=7)
    wk_index = {k: i for i, k in enumerate(weeks)}

    # Chart 1 plots inbound only, so a channel earns a series (and a legend
    # entry) only if someone actually wrote from it; outbound-only channels
    # (e.g. misaddressed replies landing in "other") still count in msgs_out.
    chans_present = [c for c, _ in CHANNELS if any(r[1] == c and r[3] for r in rows)]
    msgs_in = {c: [0] * len(weeks) for c in chans_present}
    msgs_out = [0] * len(weeks)
    wk_users = [set() for _ in weeks]
    for day, chan, user, n_in, n_out in rows:
        i = wk_index[week_of(day)]
        if n_in:
            msgs_in[chan][i] += n_in
            wk_users[i].add(user)
        msgs_out[i] += n_out

    first_week_of_user = {}
    for i, us in enumerate(wk_users):
        for u in us:
            first_week_of_user.setdefault(u, i)
    new_u = [sum(1 for u in us if first_week_of_user[u] == i) for i, us in enumerate(wk_users)]
    ret_u = [len(us) - new_u[i] for i, us in enumerate(wk_users)]

    # Daily view stops at the last complete UTC day: the pull runs mid-day,
    # so the current day would always dip.
    first_d = date.fromisoformat(min(r[0] for r in rows))
    last_d = date.fromisoformat(max(r[0] for r in rows))
    try:
        cutoff = date.fromisoformat(data.get("generated", "")[:10]) - timedelta(days=1)
    except ValueError:
        cutoff = last_d
    last_full = min(last_d, cutoff)
    days = []
    d = first_d
    while d <= last_full:
        days.append(d.isoformat())
        d += timedelta(days=1)
    d_index = {k: i for i, k in enumerate(days)}
    d_msgs_in = {c: [0] * len(days) for c in chans_present}
    d_msgs_out = [0] * len(days)
    d_users = [set() for _ in days]
    for day, chan, user, n_in, n_out in rows:
        i = d_index.get(day)
        if i is None:
            continue
        if n_in:
            d_msgs_in[chan][i] += n_in
            d_users[i].add(user)
        d_msgs_out[i] += n_out
    d_chans = [c for c in chans_present if any(d_msgs_in[c])]
    d_new = [sum(1 for u in us if users[u]["first"] == days[i]) for i, us in enumerate(d_users)]
    d_ret = [len(us) - d_new[i] for i, us in enumerate(d_users)]

    active = {u: v for u, v in users.items() if v["in"]}
    with_year = first_wk.year != last_wk.year
    return {
        "weeks": weeks,
        "labels": [week_label(k, with_year) for k in weeks],
        "days": days,
        "day_labels": [week_label(k, with_year) for k in days],
        "d_chans": d_chans,
        "d_msgs_in": d_msgs_in,
        "d_msgs_out": d_msgs_out,
        "d_new": d_new,
        "d_ret": d_ret,
        "chans": chans_present,
        "msgs_in": msgs_in,
        "msgs_out": msgs_out,
        "new_u": new_u,
        "ret_u": ret_u,
        "users": users,
        "total_in": sum(sum(v) for v in msgs_in.values()),
        "total_out": sum(msgs_out),
        "distinct": len(active),
        "repeat": sum(1 for v in active.values() if len(v["days"]) >= 2),
        "names": names,
        "day_range": (min(r[0] for r in rows), max(r[0] for r in rows)),
    }


def user_label(names, key):
    if key in names:
        return names[key]
    chan, _, rest = key.partition(" ")
    return rest or key


def esc(s):
    return html.escape(str(s), quote=True)


def tiles_html(agg):
    tiles = [
        ("Messages received", agg["total_in"], "sent to Audel, all channels"),
        ("Replies sent", agg["total_out"], "messages from Audel"),
        ("Distinct users", agg["distinct"], "sent at least one message"),
        ("Repeat users", agg["repeat"], "active on 2+ days"),
    ]
    out = []
    for label, value, hint in tiles:
        out.append(
            f'<div class="tile"><div class="tile-label">{esc(label)}</div>'
            f'<div class="tile-value">{esc(compact(value))}</div>'
            f'<div class="tile-hint">{esc(hint)}</div></div>'
        )
    return '<div class="tiles">' + "".join(out) + "</div>"


def legend_html(series):
    if len(series) < 2:
        return ""
    items = "".join(
        f'<span class="legend-item"><span class="swatch" style="background:var({s["varName"]})"></span>{esc(s["name"])}</span>'
        for s in series
    )
    return f'<div class="legend">{items}</div>'


def table_html(headers, rows_, numeric_from=1):
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = []
    for r in rows_:
        tds = "".join(
            f'<td class="{"num" if i >= numeric_from else ""}">{esc(c)}</td>'
            for i, c in enumerate(r)
        )
        trs.append(f"<tr>{tds}</tr>")
    return f'<table><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'


def details_table(headers, rows_, numeric_from=1):
    return (
        "<details><summary>Table view</summary>"
        + table_html(headers, rows_, numeric_from)
        + "</details>"
    )


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb;
  --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10);
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19;
    --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19;
  --ink: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
  --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10);
  --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--page); color: var(--ink);
  font: 14px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif;
}
.wrap { max-width: 980px; margin: 0 auto; padding: 32px 20px 64px; }
h1 { font-size: 22px; font-weight: 650; margin: 0 0 4px; }
.sub { color: var(--muted); font-size: 12.5px; margin: 0 0 24px; }
.tiles {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: 12px; margin-bottom: 20px;
}
.tile {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 14px 16px;
}
.tile-label { font-size: 12px; color: var(--ink-2); }
.tile-value { font-size: 30px; font-weight: 600; margin: 2px 0; }
.tile-hint { font-size: 11.5px; color: var(--muted); }
.card {
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 10px; padding: 18px 20px 14px; margin-bottom: 20px;
}
.card h2 { font-size: 14px; font-weight: 650; margin: 0; }
.card .desc { font-size: 12px; color: var(--muted); margin: 2px 0 10px; }
.legend { display: flex; gap: 16px; flex-wrap: wrap; margin: 0 0 6px; }
.legend-item {
  display: inline-flex; align-items: center; gap: 6px;
  font-size: 12px; color: var(--ink-2);
}
.swatch { width: 10px; height: 10px; border-radius: 3px; display: inline-block; }
svg text { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
.col-hit { outline: none; cursor: default; }
.col.lift path, .col.lift rect.seg { filter: brightness(1.08); }
details { margin-top: 8px; border-top: 1px solid var(--border); padding-top: 8px; }
summary {
  font-size: 12px; color: var(--ink-2); cursor: pointer;
  user-select: none; padding: 2px 0;
}
table { border-collapse: collapse; width: 100%; margin-top: 8px; font-size: 13px; }
th {
  text-align: left; font-size: 11px; font-weight: 600; color: var(--muted);
  border-bottom: 1px solid var(--axis); padding: 4px 10px 4px 0;
}
td { border-bottom: 1px solid var(--grid); padding: 4px 10px 4px 0; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr:last-child td { border-bottom: none; }
#tt {
  position: fixed; display: none; pointer-events: none; z-index: 10;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 10px; font-size: 12px;
  box-shadow: 0 4px 14px rgba(0,0,0,0.18); min-width: 150px;
}
#tt .tt-h { color: var(--muted); font-size: 11px; margin-bottom: 4px; }
#tt .tt-row { display: flex; align-items: center; gap: 7px; padding: 1px 0; }
#tt .tt-key { width: 12px; height: 3px; border-radius: 2px; flex: none; }
#tt .tt-val {
  font-weight: 600; font-variant-numeric: tabular-nums;
  min-width: 3ch; text-align: right;
}
#tt .tt-name { color: var(--ink-2); }
#tt .tt-total { border-top: 1px solid var(--grid); margin-top: 3px; padding-top: 3px; }
.foot { color: var(--muted); font-size: 11.5px; margin-top: 4px; }
</style>
</head>
<body>
<div class="wrap">
__BODY__
</div>
<div id="tt" role="status"></div>
<script>
const DATA = __DATA__;
const NS = "http://www.w3.org/2000/svg";
const tt = document.getElementById("tt");

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}
function fmt(n) { return n.toLocaleString("en-US"); }
function svgEl(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}
function niceStep(max) {
  const raw = Math.max(1, max) / 4;
  const p = Math.pow(10, Math.floor(Math.log10(raw)));
  for (const m of [1, 2, 5, 10]) if (m * p >= raw) return m * p;
  return 10 * p;
}
// Rounded top corners, square baseline; radius collapses on short segments.
function segPath(x, yT, yB, w, rad) {
  rad = Math.max(0, Math.min(rad, (yB - yT) / 2, w / 2));
  return `M${x},${yB} L${x},${yT + rad} Q${x},${yT} ${x + rad},${yT}` +
         ` L${x + w - rad},${yT} Q${x + w},${yT} ${x + w},${yT + rad}` +
         ` L${x + w},${yB} Z`;
}

function showTip(x, y, label, rows, total) {
  tt.textContent = "";
  const h = document.createElement("div");
  h.className = "tt-h";
  h.textContent = label;
  tt.appendChild(h);
  for (const r of rows) {
    const div = document.createElement("div");
    div.className = "tt-row";
    const key = document.createElement("span");
    key.className = "tt-key";
    key.style.background = cssVar(r.varName);
    const val = document.createElement("span");
    val.className = "tt-val";
    val.textContent = fmt(r.value);
    const name = document.createElement("span");
    name.className = "tt-name";
    name.textContent = r.name;
    div.append(key, val, name);
    tt.appendChild(div);
  }
  if (total !== null) {
    const div = document.createElement("div");
    div.className = "tt-row tt-total";
    const key = document.createElement("span");
    key.className = "tt-key";
    const val = document.createElement("span");
    val.className = "tt-val";
    val.textContent = fmt(total.value);
    const name = document.createElement("span");
    name.className = "tt-name";
    name.textContent = total.name;
    div.append(key, val, name);
    tt.appendChild(div);
  }
  tt.style.display = "block";
  const r = tt.getBoundingClientRect();
  tt.style.left = Math.min(x + 14, window.innerWidth - r.width - 8) + "px";
  tt.style.top = Math.min(y + 14, window.innerHeight - r.height - 8) + "px";
}
function hideTip() { tt.style.display = "none"; }

function stackedChart(mount, spec) {
  mount.textContent = "";
  const n = spec.labels.length;
  const totals = spec.labels.map((_, i) =>
    spec.series.reduce((a, s) => a + s.values[i], 0));
  const step = niceStep(Math.max(...totals));
  const top = Math.max(step, Math.ceil(Math.max(...totals) / step) * step);
  const W = 900, H = 300, m = { t: 26, r: 8, b: 30, l: 46 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, role: "img" });
  svg.setAttribute("aria-label", spec.title);
  svg.style.width = "100%"; svg.style.height = "auto"; svg.style.display = "block";
  const y = v => m.t + ph - (v / top) * ph;

  for (let v = step; v <= top; v += step) {
    svgEl("line", { x1: m.l, x2: W - m.r, y1: y(v), y2: y(v),
      stroke: cssVar("--grid"), "stroke-width": 1 }, svg);
    const t = svgEl("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end",
      fill: cssVar("--muted"), "font-size": 11 }, svg);
    t.style.fontVariantNumeric = "tabular-nums";
    t.textContent = fmt(v);
  }
  svgEl("line", { x1: m.l, x2: W - m.r, y1: y(0), y2: y(0),
    stroke: cssVar("--axis"), "stroke-width": 1 }, svg);
  const zero = svgEl("text", { x: m.l - 8, y: y(0) + 4, "text-anchor": "end",
    fill: cssVar("--muted"), "font-size": 11 }, svg);
  zero.textContent = "0";

  const band = pw / n, bw = Math.min(24, band * 0.6);
  const gap = 2, rad = 4;
  const capLabels = n <= 16;
  const xEvery = Math.max(1, Math.ceil(n / 12));

  spec.labels.forEach((lbl, i) => {
    const x0 = m.l + i * band + (band - bw) / 2;
    const g = svgEl("g", { class: "col" }, svg);
    const segs = [];
    let acc = 0;
    spec.series.forEach(s => {
      if (s.values[i] > 0) segs.push({ s, v0: acc, v1: acc + s.values[i] });
      acc += s.values[i];
    });
    segs.forEach((seg, si) => {
      const isTop = si === segs.length - 1;
      const yT = y(seg.v1), yB = si === 0 ? y(0) : y(seg.v0) - gap;
      if (yB - yT < 0.5) return;
      if (isTop) {
        svgEl("path", { d: segPath(x0, yT, yB, bw, rad),
          fill: cssVar(seg.s.varName) }, g);
      } else {
        svgEl("rect", { class: "seg", x: x0, y: yT, width: bw,
          height: yB - yT, fill: cssVar(seg.s.varName) }, g);
      }
    });
    if (capLabels && totals[i] > 0) {
      const t = svgEl("text", { x: x0 + bw / 2, y: y(totals[i]) - 6,
        "text-anchor": "middle", fill: cssVar("--ink-2"), "font-size": 11 }, svg);
      t.textContent = fmt(totals[i]);
    }
    if (i % xEvery === 0) {
      const t = svgEl("text", { x: m.l + i * band + band / 2, y: H - 8,
        "text-anchor": "middle", fill: cssVar("--muted"), "font-size": 11 }, svg);
      t.textContent = lbl;
    }

    const rows = spec.series.map(s => ({
      varName: s.varName, name: s.name, value: s.values[i] }));
    const total = spec.series.length > 1
      ? { name: spec.totalName, value: totals[i] } : null;
    const parts = rows.map(r => r.name + " " + fmt(r.value)).join(", ");
    const tipLabel = (spec.tipPrefix || "") + lbl;
    const hit = svgEl("rect", { class: "col-hit", x: m.l + i * band, y: m.t,
      width: band, height: ph, fill: "transparent", tabindex: 0,
      role: "img", "aria-label": `${tipLabel}: ${parts}` }, svg);
    const enter = e => { g.classList.add("lift");
      showTip(e.clientX, e.clientY, tipLabel, rows, total); };
    hit.addEventListener("pointerenter", enter);
    hit.addEventListener("pointermove", enter);
    hit.addEventListener("pointerleave", () => { g.classList.remove("lift"); hideTip(); });
    hit.addEventListener("focus", () => {
      g.classList.add("lift");
      const r = hit.getBoundingClientRect();
      showTip(r.left + r.width / 2, r.top + 20, tipLabel, rows, total);
    });
    hit.addEventListener("blur", () => { g.classList.remove("lift"); hideTip(); });
  });
  mount.appendChild(svg);
}

function renderAll() {
  for (const c of DATA.charts) {
    stackedChart(document.getElementById(c.mount), c);
  }
}
renderAll();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", renderAll);
new MutationObserver(renderAll).observe(document.documentElement,
  { attributes: true, attributeFilter: ["data-theme"] });
window.addEventListener("scroll", hideTip, { passive: true });
</script>
</body>
</html>
"""


def render(data, agg):
    ident = data.get("identity", "audel")
    title = f"{ident.capitalize()} usage"
    if agg is None:
        body = f"<h1>{esc(title)}</h1><p class='sub'>No messages found in the mind log.</p>"
        return (
            PAGE.replace("__TITLE__", esc(title))
            .replace("__BODY__", body)
            .replace("__DATA__", json.dumps({"charts": []}))
        )

    chan_names = dict(CHANNELS)
    lo, hi = agg["day_range"]
    sub = (
        f"{lo} to {hi} (UTC) &middot; {agg['total_in'] + agg['total_out']:,} messages "
        f"&middot; pulled {esc(data.get('generated', '?'))}"
    )

    # Color follows the channel: a channel keeps its weekly-chart slot in the
    # daily chart even when some channels drop out of the daily window.
    slot = {c: SLOT_VARS[i] for i, c in enumerate(agg["chans"])}
    chart1_series = [
        {"name": chan_names[c], "varName": slot[c], "values": agg["msgs_in"][c]}
        for c in agg["chans"]
    ]
    chart2_series = [
        {"name": "Returning users", "varName": "--s1", "values": agg["ret_u"]},
        {"name": "New users", "varName": "--s2", "values": agg["new_u"]},
    ]
    charts = [
        {
            "mount": "chart-msgs",
            "title": "Messages received per week",
            "labels": agg["labels"],
            "series": chart1_series,
            "totalName": "Total",
            "tipPrefix": "Week of ",
        },
        {
            "mount": "chart-users",
            "title": "Active users per week",
            "labels": agg["labels"],
            "series": chart2_series,
            "totalName": "Distinct users",
            "tipPrefix": "Week of ",
        },
    ]
    chart3_series = [
        {"name": chan_names[c], "varName": slot[c], "values": agg["d_msgs_in"][c]}
        for c in agg["d_chans"]
    ]
    chart4_series = [
        {"name": "Returning users", "varName": "--s1", "values": agg["d_ret"]},
        {"name": "New users", "varName": "--s2", "values": agg["d_new"]},
    ]
    if agg["days"]:
        charts += [
            {
                "mount": "chart-msgs-daily",
                "title": "Messages received per day",
                "labels": agg["day_labels"],
                "series": chart3_series,
                "totalName": "Total",
                "tipPrefix": "",
            },
            {
                "mount": "chart-users-daily",
                "title": "Active users per day",
                "labels": agg["day_labels"],
                "series": chart4_series,
                "totalName": "Distinct users",
                "tipPrefix": "",
            },
        ]

    t1_rows = []
    for i, wk in enumerate(agg["labels"]):
        row = [wk] + [agg["msgs_in"][c][i] for c in agg["chans"]]
        row.append(sum(agg["msgs_in"][c][i] for c in agg["chans"]))
        row.append(agg["msgs_out"][i])
        t1_rows.append(row)
    t1_head = ["Week"] + [chan_names[c] for c in agg["chans"]] + ["Total", "Replies sent"]

    t2_rows = [
        [wk, agg["new_u"][i], agg["ret_u"][i], agg["new_u"][i] + agg["ret_u"][i]]
        for i, wk in enumerate(agg["labels"])
    ]

    daily_msgs_card = daily_users_card = ""
    if agg["days"]:
        last_full = agg["days"][-1]
        t3_rows = []
        for i, dy in enumerate(agg["day_labels"]):
            row = [dy] + [agg["d_msgs_in"][c][i] for c in agg["d_chans"]]
            row.append(sum(agg["d_msgs_in"][c][i] for c in agg["d_chans"]))
            row.append(agg["d_msgs_out"][i])
            t3_rows.append(row)
        t3_head = ["Day"] + [chan_names[c] for c in agg["d_chans"]] + ["Total", "Replies sent"]
        t4_rows = [
            [dy, agg["d_new"][i], agg["d_ret"][i], agg["d_new"][i] + agg["d_ret"][i]]
            for i, dy in enumerate(agg["day_labels"])
        ]
        daily_msgs_card = f"""<div class="card">
  <h2>Messages received per day</h2>
  <p class="desc">Inbound messages to {esc(ident)} by UTC day, stacked by channel. Stops at the
  last complete day ({esc(last_full)}); the pull day is excluded as partial.</p>
  {legend_html(chart3_series)}
  <div id="chart-msgs-daily"></div>
  {details_table(t3_head, t3_rows)}
</div>"""
        daily_users_card = f"""<div class="card">
  <h2>Active users per day</h2>
  <p class="desc">Distinct people who messaged {esc(ident)} each UTC day; new means never seen
  on an earlier day. Stops at the last complete day.</p>
  {legend_html(chart4_series)}
  <div id="chart-users-daily"></div>
  {details_table(["Day", "New", "Returning", "Distinct users"], t4_rows)}
</div>"""

    users = sorted(
        (v | {"key": k} for k, v in agg["users"].items() if v["in"]),
        key=lambda v: -v["in"],
    )
    u_rows = [
        [
            user_label(agg["names"], u["key"]),
            chan_names[u["chan"]],
            u["in"],
            len(u["days"]),
            u["first"],
            u["last"],
        ]
        for u in users
    ]

    body = f"""<h1>{esc(title)}</h1>
<p class="sub">{sub}</p>
{tiles_html(agg)}
<div class="card">
  <h2>Messages received per week</h2>
  <p class="desc">Inbound messages to {esc(ident)}, stacked by channel. Weeks start Monday (UTC).</p>
  {legend_html(chart1_series)}
  <div id="chart-msgs"></div>
  {details_table(t1_head, t1_rows)}
</div>
{daily_msgs_card}
<div class="card">
  <h2>Active users per week</h2>
  <p class="desc">Distinct people who messaged {esc(ident)}; new means never seen in an earlier week.</p>
  {legend_html(chart2_series)}
  <div id="chart-users"></div>
  {details_table(["Week", "New", "Returning", "Distinct users"], t2_rows)}
</div>
{daily_users_card}
<div class="card">
  <h2>Users</h2>
  <p class="desc">Everyone who has messaged {esc(ident)}, by volume. Slack and Telegram names come
  from bridge headers; PWA names are self-declared and unverified. The same person counts once
  per channel they use.</p>
  {table_html(["User", "Channel", "Messages", "Active days", "First seen", "Last seen"],
              u_rows, numeric_from=2)}
</div>
<p class="foot">Source: {esc(data.get('log', '?'))} &middot; {data.get('skipped', 0)} unparseable steps skipped.</p>"""

    return (
        PAGE.replace("__TITLE__", esc(title))
        .replace("__BODY__", body)
        .replace("__DATA__", json.dumps({"charts": charts}, separators=(",", ":")))
    )


def main(argv):
    if len(argv) != 3:
        sys.stderr.write(__doc__)
        return 2
    with open(argv[1], encoding="utf-8") as fh:
        data = json.load(fh)
    out = render(data, build(data))
    with open(argv[2], "w", encoding="utf-8") as fh:
        fh.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
