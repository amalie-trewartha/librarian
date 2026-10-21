#!/usr/bin/env bash
# thinkers/_lib/project.sh — project mode for the monolith: long unattended
# research runs (design/long_autonomy.md). Sourced by thinkers/monolith/step.
#
# Project mode is on when <identity>/workdir/project/charter.md exists
# (`librarian-project init` sets it up) and LIBRARIAN_PROJECT_MODE is not 0.
# Everything here is deterministic shell: the runtime, not the model, decides
# when a ritual is due, when a question's default has matured, when the
# budget is spent, and it restores the read-only files and commits project/
# whether or not the model remembers to.
#
# Layout:
#   <identity>/workdir/project/   the mind's project files (a git repo)
#   <identity>/project-pristine/  read-only originals: charter.md, spec.md,
#                                 roles/, rituals/, started_at (epoch)
#   <identity>/run/project_freetime_<week>  when that week's free time opened
# Pristine files under project/ are restored from project-pristine/ on every
# wake if they changed.

_project_dir() { printf '%s' "${PROJECT_DIR:-$IDENTITY_DIR/workdir/project}"; }
_project_pristine() { printf '%s' "${PROJECT_PRISTINE_DIR:-$IDENTITY_DIR/project-pristine}"; }
_project_on() { [[ "${LIBRARIAN_PROJECT_MODE:-1}" != "0" && -f "$(_project_dir)/charter.md" ]]; }

# Epoch -> date/time in LIBRARIAN_TZ, GNU or BSD date.
_pj_date() {  # _pj_date <epoch> <format>
    TZ="${LIBRARIAN_TZ:-UTC}" date -d "@$1" "+$2" 2>/dev/null || TZ="${LIBRARIAN_TZ:-UTC}" date -r "$1" "+$2"
}
_pj_left() { local s="$1"; if (( s >= 86400 )); then printf '%sd %sh' $(( s / 86400 )) $(( s % 86400 / 3600 )); else printf '%sh %sm' $(( s / 3600 )) $(( s % 3600 / 60 )); fi; }
# Project time. PROJECT_TIME_SCALE=N runs the project clock N times faster
# than real time from the moment the project started, for accelerated test
# runs: days, weeks, rituals, the deadline, staleness, pacing and the budget
# window all follow it. 1 (the default) is real time. PROJECT_NOW pins the
# project clock and PROJECT_REAL_NOW the real one, in tests.
_pj_scale() { local k="${PROJECT_TIME_SCALE:-1}"; [[ "$k" =~ ^[1-9][0-9]*$ ]] || k=1; printf '%s' "$k"; }
_pj_real() {
    if [[ -n "${PROJECT_REAL_NOW:-}" ]]; then printf '%s' "$PROJECT_REAL_NOW"
    elif [[ -n "${PROJECT_NOW:-}" && "$(_pj_scale)" == 1 ]]; then printf '%s' "$PROJECT_NOW"
    else date +%s; fi
}
_pj_vtime() {  # _pj_vtime <real-epoch> -> project epoch
    local k; k=$(_pj_scale)
    if [[ "$k" == 1 ]]; then printf '%s' "$1"; return 0; fi
    local s; s=$(_project_started_at)
    printf '%s' $(( s + ($1 - s) * k ))
}
_pj_now() {
    if [[ -n "${PROJECT_NOW:-}" ]]; then printf '%s' "$PROJECT_NOW"; else _pj_vtime "$(_pj_real)"; fi
}
# Real seconds for a span of project seconds (at least 30 when scaled).
_pj_real_span() { local k; k=$(_pj_scale); local r=$(( $1 / k )); (( k > 1 && r < 30 )) && r=30; printf '%s' "$r"; }
_pj_mtime() {  # _pj_mtime <file> -> its mtime in project time (empty if missing)
    local m; m=$(stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null) || return 0
    _pj_vtime "$m"
}

_project_started_at() {
    local s
    s=$(cat "$(_project_pristine)/started_at" 2>/dev/null) || s=""
    [[ "$s" =~ ^[0-9]+$ ]] || s=${PROJECT_NOW:-$(date +%s)}
    printf '%s' "$s"
}
# Project week number (1-based), zero-padded.
_project_week() {  # _project_week [epoch]
    local now="${1:-$(_pj_now)}" start
    start=$(_project_started_at)
    printf '%02d' $(( (now - start) / 604800 + 1 ))
}

# The run's end (epoch), from project-pristine/end_at; empty when unset (an
# open-ended run: no phases, no final ritual).
_project_end_at() {
    local e
    e=$(cat "$(_project_pristine)/end_at" 2>/dev/null) || e=""
    [[ "$e" =~ ^[0-9]+$ ]] && printf '%s' "$e"
    return 0
}
# The final ritual is done once reports/final.md has been written at or after
# the end. A final.md drafted before the end is only a draft: on the fourth live
# run the agent assembled it early, and the existence check skipped the whole
# ritual, final cold-eyes review included.
_project_final_done() {
    local f e m
    f="$(_project_dir)/reports/final.md"; [[ -f "$f" ]] || return 1
    e=$(_project_end_at); [[ -n "$e" ]] || return 0
    m=$(_pj_mtime "$f"); [[ -n "$m" ]] && (( m >= e ))
}
# Where the run is against its deadline: build (first half), harden (second
# half), final (the last 15% or 2 days, whichever is longer), ended.
_project_phase() {  # _project_phase [epoch]
    local now="${1:-$(_pj_now)}" start end left final
    end=$(_project_end_at); [[ -n "$end" ]] || { printf 'open'; return 0; }
    start=$(_project_started_at)
    left=$(( end - now ))
    final=$(( (end - start) * 15 / 100 )); (( final < 172800 )) && final=172800
    if (( left <= 0 )); then printf 'ended'
    elif (( left <= final )); then printf 'final'
    elif (( now - start >= (end - start) / 2 )); then printf 'harden'
    else printf 'build'; fi
}
# The deliverable has been started: it exists and no longer carries the
# template's marker line.
_project_deliverable_started() {
    local f; f="$(_project_dir)/deliverable.md"
    [[ -f "$f" ]] && ! grep -q '^<!-- TEMPLATE' "$f"
}

# Restore any pristine file that changed under project/. Prints the restored
# paths (relative), one per line; empty when all is intact.
_project_guard() {
    local p d f rel
    p=$(_project_pristine); d=$(_project_dir)
    [[ -d "$p" ]] || return 0
    while IFS= read -r f; do
        rel="${f#"$p"/}"
        case "$rel" in charter.md|spec.md|roles/*|reference/*) ;; *) continue ;; esac
        if ! cmp -s "$f" "$d/$rel"; then
            mkdir -p "$(dirname "$d/$rel")"
            chmod u+w "$d/$rel" 2>/dev/null || true
            cp "$f" "$d/$rel" && chmod a-w "$d/$rel" 2>/dev/null
            printf '%s\n' "$rel"
        fi
    done < <(find "$p" -type f 2>/dev/null | sort)
    return 0
}

# STATE: first word of line 1 (active | blocked | done), defaulting to active.
_project_state() {
    local s
    s=$(head -n 1 "$(_project_dir)/STATE" 2>/dev/null | awk '{print tolower($1)}') || s=""
    case "$s" in blocked|done) printf '%s' "$s" ;; *) printf 'active' ;; esac
}

# ---------------------------------------------------------------------------
# Questions (design/long_autonomy.md, "Questions and humans")
# ---------------------------------------------------------------------------
# An entry in questions.md:
#   ### Q3 — 2026-10-05 — title — STATUS: open | answered | defaulted | moot
#   Blocking: / Default: / Default-by: / Answer: / Resolution: lines
# Q ids are stamped by the runtime (_project_number_questions). Whether an
# Answer line came from a human is decided from git, not from its text: edits
# made between wakes are committed as author "human" before each wake
# (_project_commit_outside), and `librarian-project answer` commits as "human"
# too, so an Answer line whose last author is the agent is not a human answer.

# Stamp a Q<n> id on every question header that lacks one. Idempotent.
_project_number_questions() {
    local q tmp
    q="$(_project_dir)/questions.md"
    [[ -f "$q" ]] || return 0
    grep -qE '^### ' "$q" || return 0
    tmp=$(mktemp) || return 0
    awk '
        NR == FNR { if ($0 ~ /^### Q[0-9]+ /) { n = $2; sub(/^Q/, "", n); if (n + 0 > max) max = n + 0 } next }
        /^### / && /STATUS:/ && $0 !~ /^### Q[0-9]+ / {
            st = substr($0, index($0, "STATUS:")); if (index(st, "|")) { print; next }
            max++; print "### Q" max " — " substr($0, 5); next
        }
        { print }' "$q" "$q" > "$tmp" && ! cmp -s "$tmp" "$q" && cat "$tmp" > "$q"
    rm -f "$tmp"
    return 0
}

# questions.md -> records, one question per line, fields split by \037 (not
# tab: tab is IFS whitespace, so `read` would merge empty fields):
#   id, title, status, blocking, default-by, default, answer, resolution,
#   opened, answer-line-number
_project_questions() {
    local q
    q="$(_project_dir)/questions.md"
    [[ -f "$q" ]] || return 0
    awk '
        function clean(x) { gsub(/\t/, " ", x); sub(/^[[:space:]]+/, "", x); sub(/[[:space:]]+$/, "", x); return x }
        function flush() {
            if (t != "") printf "%s\037%s\037%s\037%s\037%s\037%s\037%s\037%s\037%s\037%s\n", id, t, st, b, db, df, an, rs, op, al
            t = ""
        }
        /^### / && /STATUS:/ {
            flush(); h = substr($0, 5); i = index(h, "STATUS:")
            st = tolower(substr(h, i + 7))
            if (index(st, "|")) { t = ""; next }   # the format example, not a question
            gsub(/[^a-z]/, "", st)
            t = substr(h, 1, i - 1); sub(/[[:space:]]*(—|-)+[[:space:]]*$/, "", t)
            id = ""; if (match(t, /^Q[0-9]+/)) { id = substr(t, 1, RLENGTH); t = substr(t, RLENGTH + 1); sub(/^[[:space:]]*(—|-)+[[:space:]]*/, "", t) }
            op = ""; if (match(t, /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/)) { op = substr(t, 1, 10); t = substr(t, 11); sub(/^[[:space:]]*(—|-)+[[:space:]]*/, "", t) }
            t = clean(t); b = "no"; db = ""; df = ""; an = ""; rs = ""; al = ""; next
        }
        /^### / { flush(); next }
        t != "" && /^Blocking:/ { b = tolower($2) }
        t != "" && /^Default-by:/ { db = $2 }
        # "Default (revised 2026-10-16): ..." counts too; the last one wins. On a live
        # run a revised default showed as "none given" in the status view.
        t != "" && /^Default( *\([^)]*\))?:/ { x = $0; sub(/^Default( *\([^)]*\))?:/, "", x); df = clean(x) }
        t != "" && /^Answer:/ { an = clean(substr($0, 8)); if (an ~ /^\((filled in by a human|a human writes|none)/) an = ""; al = NR }   # () = the template placeholder
        t != "" && /^Resolution:/ { rs = clean(substr($0, 12)) }
        END { flush() }' "$q"
}

# Ids of questions whose Answer line was last written by a human commit.
_project_human_answers() {
    local d
    d=$(_project_dir)
    [[ -d "$d/.git" ]] || return 0
    local blame
    blame=$(git -C "$d" blame --line-porcelain -- questions.md 2>/dev/null) || return 0
    local id t st b db df an rs op al author
    while IFS=$'\037' read -r id t st b db df an rs op al; do
        [[ -n "$an" && -n "$al" && -n "$id" ]] || continue
        author=$(printf '%s\n' "$blame" | awk -v want="$al" '
            /^[0-9a-f]{40} / { line = $3 } /^author / && line == want { sub(/^author /, ""); print; exit }')
        [[ "$author" == human ]] && printf '%s\n' "$id"
    done < <(_project_questions)
    return 0
}

# How each question stands, for humans: \037-split id, kind, title, detail, where
# kind is one of: open, human-waiting (answered by a human, not yet applied),
# human (closed with a human answer), default, moot, unverified (marked
# answered, but no human wrote the answer).
_project_question_rows() {
    local humans id t st b db df an rs op al kind detail
    humans=" $(_project_human_answers | tr '\n' ' ') "
    while IFS=$'\037' read -r id t st b db df an rs op al; do
        # A human answer needs an id and answer text: an unnumbered question
        # (written mid-wake, stamped at the next wake) matched an empty id
        # here and showed as "answered by a human" on a live run.
        local h=0; [[ -n "$id" && -n "$an" && "$humans" == *" $id "* ]] && h=1
        case "$st" in
            open) if (( h )); then kind=human-waiting; detail="human answer: $an"; else kind=open
                  detail="blocking: $b; default-by: ${db:-MISSING}; default: ${df:-none given}"; fi ;;
            answered) if (( h )); then kind=human; detail="$an"; else kind=unverified; detail="${an:-no answer text}"; fi ;;
            defaulted) kind=default; detail="${rs:-default: ${df:-not recorded}}" ;;
            *) kind=moot; detail="${rs:-moot}" ;;
        esac
        printf '%s\037%s\037%s\037%s\037%s\037%s\037%s\n' "${id:-Q?}" "$kind" "$t" "$detail" "$op" "$b" "$db"
    done < <(_project_questions)
}

# The default to apply early because the mind is fully blocked (STATE blocked):
# the earliest-dated open question, non-blocking ones first, then blocking.
# Nothing while a default is already due or a human answer is waiting, and
# never for "Default-by: never". Defaults otherwise wait for their date, which
# the charter sets a few days out; a live run sat idle for 5 h behind defaults
# 4-6 days away. One per wake: the next wake pulls the next if still blocked.
# Prints id<US>title<US>default-by, or nothing. PROJECT_BLOCKED_DEFAULT=0 = off.
_project_blocked_default() {
    [[ "${PROJECT_BLOCKED_DEFAULT:-1}" != 0 && "$(_project_state)" == blocked ]] || return 0
    local today; today=$(_pj_date "$(_pj_now)" %F)
    _project_question_rows | awk -F'\037' -v today="$today" '
        $2 == "human-waiting" { due = 1 }
        $2 == "open" && $7 ~ /^[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]$/ {
            if ($7 <= today) due = 1
            k = ($6 == "yes" ? "1" : "0") $7
            if (pick == "" || k < best) { best = k; pick = $1 "\037" $3 "\037" $7 }
        }
        END { if (!due && pick != "") print pick }'
}

# The questions block for human-facing status: every open question, loudly,
# for as long as it is open. $1 = "brief" for a one-screen version.
_project_question_banner() {
    local today rows open=0 id kind t detail op b db when
    today=$(_pj_date "$(_pj_now)" %F)
    rows=$(_project_question_rows)
    open=$(printf '%s\n' "$rows" | awk -F'\037' '$2 == "open" || $2 == "human-waiting"' | grep -c . || true)
    local name="${IDENTITY_NAME:-<name>}" early
    early=$(_project_blocked_default | cut -d$'\037' -f1)
    if (( open == 0 )); then
        printf 'Open questions: none.\n'
    else
        printf '!!! %s OPEN QUESTION(S) FOR A HUMAN — answer with: librarian-project answer %s <Qn> "<answer>"\n' "$open" "$name"
        while IFS=$'\037' read -r id kind t detail op b db; do
            case "$kind" in
                open)
                    if [[ -z "$db" ]]; then when="no default date set"
                    elif [[ "$db" == never ]]; then when="will NOT default; blocked until a human answers"
                    elif [[ -n "$early" && "$id" == "$early" ]]; then when="the agent is blocked, so it applies this default at its next wake (date was $db)"
                    elif [[ "$db" > "$today" ]]; then when="default applies on $db"
                    else when="default due now ($db); the agent will apply it"; fi
                    printf '  %s%s  %s\n      opened %s; %s\n      default: %s\n' "$id" "$([[ "$b" == yes ]] && printf ' [BLOCKING]')" "$t" "${op:-?}" "$when" \
                        "$(printf '%s' "$detail" | sed 's/.*default: //')" ;;
                human-waiting)
                    printf '  %s  %s\n      answered by a human; the agent applies it on its next wake\n' "$id" "$t" ;;
            esac
        done < <(printf '%s\n' "$rows" | awk -F'\037' '$2 == "open" || $2 == "human-waiting"')
    fi
    local closed unverified
    closed=$(printf '%s\n' "$rows" | awk -F'\037' '$2 == "human" || $2 == "default" || $2 == "moot" || $2 == "unverified"' | grep -c . || true)
    unverified=$(printf '%s\n' "$rows" | awk -F'\037' '$2 == "unverified" {print $1}' | tr '\n' ' ')
    if [[ "${1:-}" != brief ]] || (( closed > 0 )); then
        printf 'Closed questions: %s (how each was resolved: project/questions-summary.md, or librarian-project questions %s --closed)\n' "$closed" "$name"
    fi
    [[ -n "$unverified" ]] && printf '!!! Marked answered, but no human wrote the answer: %s\n' "$unverified"
    return 0
}

# Write project/questions-summary.md: open questions first, then every closed
# question with how it was closed (human answer, default, moot). Generated on
# every wake; edits to it are overwritten.
_project_write_summary() {
    local d out rows id kind t detail op b db
    d=$(_project_dir); out="$d/questions-summary.md"
    rows=$(_project_question_rows)
    {
        printf '# Questions: summary\n\nGenerated by the runtime from questions.md on every wake (%s). Do not edit; edit questions.md.\n' "$(_pj_date "$(_pj_now)" '%Y-%m-%d %H:%M %Z')"
        printf 'To answer an open question: librarian-project answer %s <Qn> "<answer>"\n\n' "${IDENTITY_NAME:-<name>}"
        printf '## Open: waiting on a human\n\n'
        printf '%s\n' "$rows" | awk -F'\037' '
            $2 == "open" { n++; printf "- **%s**%s %s  \n  opened %s; default-by %s. %s\n", $1, ($6 == "yes" ? " (blocking)" : ""), $3, $5, ($7 == "" ? "MISSING" : $7), $4 }
            $2 == "human-waiting" { n++; printf "- **%s** %s  \n  A human answered; the agent applies it on its next wake. %s\n", $1, $3, $4 }
            END { if (!n) print "None." }'
        printf '\n## Closed\n\n| Id | Question | Opened | Closed by | Answer or default used |\n|---|---|---|---|---|\n'
        printf '%s\n' "$rows" | awk -F'\037' '
            function esc(x) { gsub(/\|/, "\\|", x); return x }
            $2 == "human" { printf "| %s | %s | %s | Human answer | %s |\n", $1, esc($3), $5, esc($4) }
            $2 == "default" { printf "| %s | %s | %s | Default (no human answer) | %s |\n", $1, esc($3), $5, esc($4) }
            $2 == "moot" { printf "| %s | %s | %s | Moot | %s |\n", $1, esc($3), $5, esc($4) }
            $2 == "unverified" { printf "| %s | %s | %s | UNVERIFIED: marked answered, no human answer found | %s |\n", $1, esc($3), $5, esc($4) }'
    } > "$out.tmp" && mv "$out.tmp" "$out"
    return 0
}

# Commit edits made to project/ between wakes, as author "human", before the
# wake runs. Between wakes only humans write here (the monolith is the only
# writer during a wake, and it commits on the way out), so this is what makes
# a human's answer provable later. A wake that crashed before its commit would
# also land here; the message says so.
_project_commit_outside() {
    local d
    d=$(_project_dir)
    command -v git >/dev/null 2>&1 && [[ -d "$d/.git" ]] || return 0
    [[ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ]] || return 0
    git -C "$d" add -A >/dev/null 2>&1 || return 0
    git -C "$d" -c user.name=human -c user.email=human@librarian.local \
        commit -q -m "edits made between wakes (a human, or a wake that crashed before committing)" >/dev/null 2>&1 || true
    return 0
}

# ---------------------------------------------------------------------------
# Token budget
# ---------------------------------------------------------------------------
# What budgets count is defined once, in `llm --spend` (bin/llm): tokens with
# cache reads weighted by PROJECT_CACHE_READ_WEIGHT (default 0.1, about their
# price relative to fresh input), or, when a dollar cap is set, estimated
# dollars from each call's cost_usd (micro-dollars internally). Before this,
# cache reads counted in full and a mostly cached run read as about 4x its
# cost; and a token is not a token across models, which dollars fix (a
# cheap delegate saves budget only when the budget is in dollars).
_project_ledger() { printf '%s' "${LLM_USAGE_LEDGER:-$IDENTITY_DIR/usage/llm.jsonl}"; }
_project_unit() {
    if [[ "${PROJECT_DAILY_USD:-}${PROJECT_TOTAL_USD:-}${PROJECT_WAKE_USD:-}" =~ [1-9] ]]; then printf 'usd'; else printf 'tokens'; fi
}
_pj_usd_micro() { awk -v v="${1:-0}" 'BEGIN { if (v+0 > 0) printf "%d", v * 1000000; else printf "0" }'; }
# Caps in budget units (tokens, or micro-dollars when the unit is usd); 0 = none.
_project_cap_daily() {
    if [[ "$(_project_unit)" == usd ]]; then _pj_usd_micro "${PROJECT_DAILY_USD:-0}"
    else local c="${PROJECT_DAILY_TOKENS:-0}"; [[ "$c" =~ ^[0-9]+$ ]] || c=0; printf '%s' "$c"; fi
}
_project_cap_total() {
    if [[ "$(_project_unit)" == usd ]]; then _pj_usd_micro "${PROJECT_TOTAL_USD:-0}"
    else local c="${PROJECT_TOTAL_TOKENS:-0}"; [[ "$c" =~ ^[0-9]+$ ]] || c=0; printf '%s' "$c"; fi
}
_project_fmt() {  # _project_fmt <units> -> "1234567 tokens" or "$12.34"
    if [[ "$(_project_unit)" == usd ]]; then awk -v v="${1:-0}" 'BEGIN { printf "$%.2f", v / 1000000 }'
    else printf '%s tokens' "${1:-0}"; fi
}
_pj_spend() { PROJECT_BUDGET_UNIT="$(_project_unit)" llm --spend --ledger "$(_project_ledger)" "$@" 2>/dev/null || printf '0'; }
# Spend over the last project day (86400 real seconds, or less when scaled).
_project_tokens_24h() {
    _pj_spend --since "$(TZ=UTC _pj_date $(( $(_pj_real) - 86400 / $(_pj_scale) )) '%Y-%m-%dT%H:%M:%SZ')"
}
# Ledger line count now, and spend on the lines after a given count: the
# step brackets its run with these to learn what one wake cost.
_project_ledger_lines() { local l; l=$(_project_ledger); [[ -f "$l" ]] && wc -l < "$l" | tr -d ' ' || printf '0'; }
_project_tokens_after() { _pj_spend --after "${1:-0}"; }  # _project_tokens_after <line-count>
# Spend since the project started: the whole-run total.
_project_tokens_total() { _pj_spend --since "$(TZ=UTC _pj_date "$(_project_started_at)" '%Y-%m-%dT%H:%M:%SZ')"; }
# Over budget: the daily cap or the whole-run cap. The step skips the model
# call entirely while over, so a cap is hard up to the wake that crossed it.
_project_over_budget() {
    local cap total
    cap=$(_project_cap_daily); total=$(_project_cap_total)
    if (( total > 0 )) && (( $(_project_tokens_total) >= total )); then return 0; fi
    (( cap > 0 )) || return 1
    (( $(_project_tokens_24h) >= cap ))
}

# Budget hold: a free pause before the hard cap. On the live trial
# (2026-10-15/16) the mind chose to rest at about 90% of the daily dollar cap
# to keep the rest for rituals, but STATE stayed active, so every rest wake was
# a full model call: about $0.27 every 5 minutes, 127 rest wakes overnight
# against 8 that worked, about $3/h. The runtime now keeps that reserve
# itself. At PROJECT_BUDGET_HOLD of the daily cap (a fraction, default 0.9;
# 0 or 1 or more = off) a timer wake makes no model call unless a ritual, a
# matured default or a human answer is due, and checks again every
# PROJECT_BUDGET_HOLD_CHECK project seconds (default 600). The cap is a
# rolling day, so work resumes as soon as spend falls back under the line.
_project_hold_line() {  # the hold line in budget units; 0 = no hold
    local cap; cap=$(_project_cap_daily)
    (( cap > 0 )) || { printf '0'; return 0; }
    awk -v c="$cap" -v f="${PROJECT_BUDGET_HOLD:-0.9}" 'BEGIN { if (f+0 > 0 && f+0 < 1) printf "%d", c * f; else printf "0" }'
}
_project_budget_hold() {
    local line; line=$(_project_hold_line)
    (( line > 0 )) || return 1
    (( $(_project_tokens_24h) >= line ))
}
# Should this wake skip the model for the budget hold? $1 = wake mode: a
# reactive wake (someone wrote to the mind) always runs.
_project_should_hold() {
    [[ "${1:-}" == reactive ]] && return 1
    _project_budget_hold || return 1
    [[ -n "$(_project_due_ritual)" ]] && return 1
    local sig; sig=$(_project_signals)
    [[ "$sig" == *"- DEFAULT DUE"* || "$sig" == *"- HUMAN ANSWER"* ]] && return 1
    return 0
}

# The ritual due now, if any, as "<kind> <arg>": "weekly 03", "daily
# 2026-10-05", "freetime 02 <until-epoch>". Weekly outranks daily outranks
# free time. Empty when nothing is due. Done-ness is the existence of the
# ritual's output file (for final, one written after the end), so a ritual
# cut short by a crash is simply due again.
_project_due_ritual() {
    local d now start at at_m now_m bdate week prev fdir started
    d=$(_project_dir); now=$(_pj_now); start=$(_project_started_at)
    week=$(_project_week "$now")
    prev=$(printf '%02d' $(( 10#$week - 1 )))
    local phase; phase=$(_project_phase "$now")
    # Past the end, the final ritual is the only one: then the run rests.
    if [[ "$phase" == ended ]]; then
        _project_final_done || printf 'final final'
        return 0
    fi
    if (( 10#$week >= 2 )) && [[ ! -f "$d/reports/week-$prev.md" ]]; then
        printf 'weekly %s' "$prev"; return 0
    fi
    at="${PROJECT_DAILY_AT:-21:00}"
    at_m=$(( 10#${at%:*} * 60 + 10#${at#*:} ))
    now_m=$(( 10#$(_pj_date "$now" %H) * 60 + 10#$(_pj_date "$now" %M) ))
    # The latest daily boundary (PROJECT_DAILY_AT local) at or before now; its
    # date names the day being closed. A project started after it owes nothing.
    local boundary=$(( now - ((now_m - at_m + 1440) % 1440) * 60 - 10#$(_pj_date "$now" %S) ))
    bdate=$(_pj_date "$boundary" %F)
    if (( boundary > start )) && [[ ! -f "$d/daily/$bdate.md" ]]; then
        printf 'daily %s' "$bdate"; return 0
    fi
    if [[ "${PROJECT_FREETIME:-1}" == "1" && "$phase" != final ]] && (( (now - start) % 604800 >= ${PROJECT_FREETIME_DAY:-5} * 86400 )); then
        fdir="$d/free-time/week-$week"
        [[ -f "$fdir/report.md" ]] && return 0
        started=$(cat "$IDENTITY_DIR/run/project_freetime_$week" 2>/dev/null) || started=""
        if [[ ! "$started" =~ ^[0-9]+$ ]]; then
            started="$now"
            mkdir -p "$IDENTITY_DIR/run" && printf '%s' "$now" > "$IDENTITY_DIR/run/project_freetime_$week" 2>/dev/null || true
        fi
        (( now - started < 86400 )) && printf 'freetime %s %s' "$week" $(( started + 43200 ))
    fi
    return 0
}

# Ritual instructions, from project-pristine/rituals/<kind>.md.
_project_ritual_text() {  # _project_ritual_text <kind> <arg> [until]
    local f
    f="$(_project_pristine)/rituals/$1.md"
    [[ -f "$f" ]] || return 0
    local until_s=""
    [[ -n "${3:-}" ]] && until_s=$(_pj_date "$3" '%a %Y-%m-%d %H:%M %Z')
    sed -e "s/{{date}}/$2/g" -e "s/{{week}}/$2/g" -e "s/{{until}}/$until_s/g" "$f"
}

# The project block of the wake prompt: charter, spec, memory, journal tail,
# state. Stable parts first, so the cached prompt prefix survives. Two
# cache-break markers (bin/llm, LLM_CACHE_BREAK) cut it where the rate of
# change steps up: after the charter, spec and references, which change only
# when a human edits them or a new brief arrives, and after project-memory.md,
# which changes only when the mind edits it. Everything below the second
# marker may change every wake: the workspace counts, the memory pack, the
# journal tail, the clock and STATE. The pack used to sit above project memory,
# and since it is rebuilt every wake it took the 12K tokens of project memory
# out of the cached prefix with it (run A: 5 of 1,155 wake-first calls read
# any cache). On Anthropic-format providers the markers become cache
# breakpoints; everywhere else bin/llm drops the marker lines.
_PJ_CACHE_BREAK='<<<llm-cache-break>>>'   # must match LLM_CACHE_BREAK in bin/llm
_project_section() {  # _project_section [librarian-pack] [workspace-section]
    local d now start pack="${1:-}" workspace="${2:-}" jn="${PROJECT_JOURNAL_ENTRIES:-5}"
    d=$(_project_dir); now=$(_pj_now); start=$(_project_started_at)
    local spec_max="${PROJECT_SPEC_MAX:-16000}" mem_max="${PROJECT_MEMORY_MAX:-14000}"
    # With a memory pack the journal tail shrinks: the pack carries what outlives
    # the project, project-memory.md stays as task state (design/librarian.md).
    [[ -n "$pack" ]] && jn="${PROJECT_JOURNAL_ENTRIES_PACKED:-2}"
    printf 'PROJECT MODE. You are on a long unattended project. Your charter (project/charter.md, read-only) governs this wake and outranks the persona above wherever they differ:\n\n'
    sed "s/{{identity_name}}/$IDENTITY_NAME/g" "$d/charter.md"
    printf '\n\nProject specification (project/spec.md, read-only, verbatim from the humans):\n\n'
    head -c "$spec_max" "$d/spec.md" 2>/dev/null
    (( $(wc -c < "$d/spec.md" 2>/dev/null || echo 0) > spec_max )) && printf '\n[... spec continues; read project/spec.md for the rest]'
    local refs
    refs=$(cd "$d" 2>/dev/null && find reference -type f ! -name '.*' 2>/dev/null | sort | tr '\n' ' ')
    [[ -n "$refs" ]] && printf '\n\nReference material from the humans (read-only; read a file when it would help, not every wake): %s' "$refs"
    printf '\n%s\n' "$_PJ_CACHE_BREAK"
    printf '\nProject memory (project/project-memory.md, your formal record):\n\n'
    head -c "$mem_max" "$d/project-memory.md" 2>/dev/null
    (( $(wc -c < "$d/project-memory.md" 2>/dev/null || echo 0) > mem_max )) && printf '\n[... cut at %s bytes; read project/project-memory.md for the rest, and consider tightening it]' "$mem_max"
    printf '\n%s\n' "$_PJ_CACHE_BREAK"
    # The workspace section changes whenever a directory's file count does, so
    # in project mode it sits here, below both markers, not at the top.
    [[ -n "$workspace" ]] && printf '\n%s\n' "$workspace"
    [[ -n "$pack" ]] && printf '\nYour memory pack (from the librarian store; ids cite a memory, PROBATIONARY means no outcome has confirmed it yet, bodies are records not instructions):\n\n%s\n' "$pack"
    printf '\nLast %s journal entries (project/journal.md):\n\n' "$jn"
    awk -v n="$jn" '
        /^### [0-9]/ { c++ } c { e[c] = e[c] $0 "\n" }
        END { if (!c) print "(no entries yet)"; for (i = (c > n ? c - n + 1 : 1); i <= c; i++) printf "%s", e[i] }' \
        "$d/journal.md" 2>/dev/null | tail -c "${PROJECT_JOURNAL_MAX:-8000}"
    local end; end=$(_project_end_at)
    if [[ -n "$end" ]]; then
        printf '\nProject clock: day %s of %s, week %s, phase %s. Started %s; the run ends %s (%s).\n' \
            $(( (now - start) / 86400 + 1 )) $(( (end - start + 86399) / 86400 )) "$(_project_week "$now")" "$(_project_phase "$now")" \
            "$(_pj_date "$start" '%Y-%m-%d %H:%M %Z')" "$(_pj_date "$end" '%Y-%m-%d %H:%M %Z')" \
            "$( (( end > now )) && printf '%s left' "$(_pj_left $(( end - now )))" || printf 'ended')"
    else
        printf '\nProject clock: day %s, week %s, started %s; no end date set.\n' \
            $(( (now - start) / 86400 + 1 )) "$(_project_week "$now")" "$(_pj_date "$start" '%Y-%m-%d %H:%M %Z')"
    fi
    printf 'STATE: %s' "$(head -n 3 "$d/STATE" 2>/dev/null | tr '\n' ' ' | cut -c1-300)"
    printf '\n'
    return 0
}

# Routing-signal lines for project mode. $1 = files the guard restored.
_project_signals() {
    local restored="${1:-}" d now today ritual kind arg until q title st b db
    d=$(_project_dir); now=$(_pj_now); today=$(_pj_date "$now" %F)
    if [[ "$(_pj_scale)" != 1 ]]; then
        printf -- '- PROJECT TIME runs %sx faster than real time (an accelerated run). It is now %s in project time. Use project time for every date you write (journal headers, Default-by dates); the system clock (`date`) shows real time and is wrong for this.\n' \
            "$(_pj_scale)" "$(_pj_date "$now" '%A %Y-%m-%d %H:%M %Z')"
    fi
    if [[ -n "$restored" ]]; then
        printf -- '- GUARD: these read-only files had changed and were restored from the pristine copy: %s. Never edit them; revise how you work with `librarian identity edit`.\n' "$(printf '%s' "$restored" | tr '\n' ' ')"
    fi
    ritual=$(_project_due_ritual)
    if [[ -n "$ritual" ]]; then
        read -r kind arg until <<< "$ritual"
        case "$kind" in
            freetime)
                if (( now < until )); then
                    printf -- '- FREE TIME is open (weekly). Instructions:\n'
                else
                    printf -- '- FREE TIME has ended: write project/free-time/week-%s/report.md now, briefly, and return to the project.\n- Instructions were:\n' "$arg"
                fi ;;
            *) printf -- '- RITUAL DUE (%s). It outranks normal work this wake. Instructions:\n' "$kind" ;;
        esac
        _project_ritual_text "$kind" "$arg" "$until" | sed 's/^/    /'
    fi
    local open=0 blocking=0 nodef="" matured="" waiting="" unverified="" id kind t detail op bl db
    while IFS=$'\037' read -r id kind t detail op bl db; do
        case "$kind" in
            open)
                open=$(( open + 1 )); [[ "$bl" == yes ]] && blocking=$(( blocking + 1 ))
                if [[ -z "$db" ]]; then nodef="${nodef}${id} \"${t}\"; "
                elif [[ "$db" != never && ! "$db" > "$today" ]]; then matured="${matured}${id} \"${t}\" (default-by ${db}); "
                fi ;;
            human-waiting) waiting="${waiting}${id} \"${t}\"; " ;;
            unverified) unverified="${unverified}${id} " ;;
        esac
    done < <(_project_question_rows)
    waiting="${waiting%; }"; matured="${matured%; }"; nodef="${nodef%; }"; unverified="${unverified% }"
    if [[ -n "$waiting" ]]; then
        printf -- '- HUMAN ANSWER: a human answered %s. Apply it now, ahead of other work: update project-memory.md (and anything downstream it changes), add a "Resolution: YYYY-MM-DD human answer applied: <what changed>" line, mark it STATUS: answered, and journal it. Never edit the Answer line.\n' "$waiting"
    fi
    if [[ -n "$matured" ]]; then
        printf -- '- DEFAULT DUE: no human answered %s by its date. Apply its default now: record the call and its risk in project-memory.md under "Interpretation calls made without a human", add a "Resolution: YYYY-MM-DD default applied: <the default used>" line, mark it STATUS: defaulted, and unpark the work behind it.\n' "$matured"
    fi
    local early eid et edb
    early=$(_project_blocked_default)
    if [[ -n "$early" ]]; then
        IFS=$'\037' read -r eid et edb <<< "$early"
        printf -- '- DEFAULT DUE (early): STATE is blocked, so instead of idling until %s you apply the earliest open default now: %s "%s". Record the call and its risk in project-memory.md under "Interpretation calls made without a human", add a "Resolution: YYYY-MM-DD default applied early (agent blocked): <the default used>" line, mark it STATUS: defaulted, and unpark the work behind it. If nothing can move after that, keep STATE blocked and the next wake brings the next default forward.\n' "$edb" "$eid" "$et"
    fi
    [[ -n "$unverified" ]] && printf -- '- QUESTION RECORD WRONG: %s is marked answered, but no human wrote its Answer line. Only a human answers. If you applied a default, mark it STATUS: defaulted with a Resolution line; otherwise set it back to open.\n' "$unverified"
    [[ -n "$nodef" ]] && printf -- '- These open questions have no Default-by line, so they can never resolve without a human: %s. Add a default and a date (or Default-by: never, on purpose).\n' "$nodef"
    (( open > 0 )) && printf -- '- Questions: %s open, %s blocking. Humans see every open question in their status view. Work an unblocked thread while they wait.\n' "$open" "$blocking"
    local phase start end left dl_stale="${PROJECT_DELIVERABLE_STALE_HOURS:-48}" dl_by="${PROJECT_DELIVERABLE_BY_DAYS:-1}" dm
    phase=$(_project_phase "$now"); start=$(_project_started_at); end=$(_project_end_at)
    [[ -n "$end" ]] && left=$(_pj_left $(( end > now ? end - now : 0 )))
    case "$phase" in
        build) printf -- '- DEADLINE: %s left in the run (phase: build). Spend effort where it moves project/deliverable.md toward a complete answer to the spec.\n' "$left" ;;
        harden) printf -- '- DEADLINE: %s left (phase: harden, second half). Prefer checking and stress-testing what the deliverable rests on (sources, uncertainty, sensitivity) over new scope.\n' "$left" ;;
        final) printf -- '- FINAL STRETCH: %s left. No new scope. Finish the deliverable: every number sourced or marked, every caveat explicit, open questions closed or defaulted, so it stands on its own when the run ends.\n' "$left" ;;
        ended) printf -- '- THE RUN HAS ENDED (%s). Do the final ritual if it is due; after that, set STATE to done.\n' "$(_pj_date "$end" '%Y-%m-%d %H:%M %Z')" ;;
    esac
    if ! _project_deliverable_started; then
        (( now - start >= dl_by * 86400 )) && printf -- '- DELIVERABLE MISSING: day %s and project/deliverable.md is still the template. Build the crude end-to-end model now (function: model) and write its headline number into a first full draft, however rough, with placeholders and caveats marked. Do this before any further exploration.\n' $(( (now - start) / 86400 + 1 ))
    else
        dm=$(_pj_mtime "$d/deliverable.md"); [[ -n "$dm" ]] || dm="$now"
        if [[ "$(_project_state)" == active && "$phase" != ended ]] && (( now - dm > dl_stale * 3600 )); then
            printf -- '- DELIVERABLE STALE: project/deliverable.md has not changed in %sh. Fold what the journal learned since into it.\n' $(( (now - dm) / 3600 ))
        fi
    fi
    local state; state=$(_project_state)
    case "$state" in
        blocked|done)
            printf -- '- STATE is %s, so wakes run at a rest pace. Rest (idle) unless a ritual or a default is due or you see a genuinely new way forward. If you do, set STATE back to active first.\n' "$state" ;;
        *)
            local jm stall_h="${PROJECT_STALL_HOURS:-12}"
            jm=$(_pj_mtime "$d/journal.md"); [[ -n "$jm" ]] || jm="$now"
            if (( now - jm > stall_h * 3600 )); then
                printf -- '- STALL: STATE is active but the journal has not changed in %sh. Re-read the spec, pick the smallest checkable next step and do it, or write the blocker to questions.md and set STATE to blocked. Do not keep circling.\n' $(( (now - jm) / 3600 ))
            fi
            local idle_n nudge="${PROJECT_IDLE_NUDGE:-2}"
            idle_n=$(_project_idle_streak)
            if [[ "$nudge" =~ ^[0-9]+$ ]] && (( nudge > 0 && idle_n >= nudge )); then
                printf -- '- IDLE: your last %s wakes changed no project file (STATE, librarian.md and questions-summary.md do not count), and each was a paid model call. The runtime now spaces these wakes out, and after %s idle wakes in a row it skips the model until something under project/ changes, a ritual, default or human answer is due, or an hour passes. If every thread is parked behind a question or a default date, set STATE to blocked: a blocked mind rests for free, still wakes for rituals, human answers and due defaults, and the runtime applies the earliest open default early. Set STATE back to active when something can move.\n' "$idle_n" "${PROJECT_IDLE_SKIP_STREAK:-3}"
            fi ;;
    esac
    local wceil; wceil=$(_project_wake_ceiling)
    if (( wceil > 0 )); then
        printf -- '- WAKE BUDGET: about %s for this whole wake, subagents included. One model step here costs roughly 20K to 40K tokens (with cache reads counted at a fraction), and a blind run 100K to 400K; blind and delegate refuse to start once the wake has spent its share. Run at most one blind subagent per wake unless the budget clearly allows more; a delegate on a cheaper model costs a fraction.\n' "$(_project_fmt "$wceil")"
    fi
    local total tused
    total=$(_project_cap_total)
    if (( total > 0 )); then
        tused=$(_project_tokens_total)
        if (( tused * 10 >= total * 7 )); then
            printf -- '- RUN BUDGET: %s of the %s for the whole run are spent. Spend the rest where it most improves the deliverable; leave enough for the final ritual.\n' "$(_project_fmt "$tused")" "$(_project_fmt "$total")"
        fi
    fi
    local cap used
    cap=$(_project_cap_daily)
    if (( cap > 0 )); then
        used=$(_project_tokens_24h)
        if (( used >= cap )); then
            printf -- '- BUDGET SPENT: %s of %s used in the last project day. Wakes are slowed until usage falls. Do only rituals and the cheapest essential work; prefer idle.\n' "$(_project_fmt "$used")" "$(_project_fmt "$cap")"
        else
            local line; line=$(_project_hold_line)
            if (( line > 0 && used >= line )); then
                printf -- '- BUDGET HOLD: %s of %s for the day used, past the %s hold line. Ordinary wakes are paused for free and the rest is kept for rituals; this wake runs because a ritual, a default or a human answer is due. Do that, cheaply, and nothing else.\n' "$(_project_fmt "$used")" "$(_project_fmt "$cap")" "$(_project_fmt "$line")"
            elif (( used * 10 >= cap * 8 )); then
                if (( line > 0 )); then
                    printf -- '- BUDGET: %s of %s for the day used. Favor cheap, high-value steps. At %s the runtime pauses ordinary wakes for free and keeps the rest for rituals, so keep working until then: do not rest to save budget, because a rest wake costs as much as a cheap step.\n' "$(_project_fmt "$used")" "$(_project_fmt "$cap")" "$(_project_fmt "$line")"
                else
                    printf -- '- BUDGET: %s of %s for the day used. Favor cheap, high-value steps.\n' "$(_project_fmt "$used")" "$(_project_fmt "$cap")"
                fi
            fi
        fi
    fi
    return 0
}

# Tokens this wake may spend, blind subagents included (0 = no ceiling):
# PROJECT_WAKE_TOKENS, else half the daily cap; never more than what is left
# of the whole-run cap. A step cap bounds one model run, not a wake: on the
# first live run one wake started two blind explorers and spent 1.3M tokens.
_project_wake_ceiling() {
    local w cap total left
    if [[ "$(_project_unit)" == usd ]]; then w=$(_pj_usd_micro "${PROJECT_WAKE_USD:-0}"); (( w > 0 )) || w=""
    else w="${PROJECT_WAKE_TOKENS:-}"; fi
    cap=$(_project_cap_daily); total=$(_project_cap_total)
    if [[ ! "$w" =~ ^[0-9]+$ ]]; then w=$(( cap / 2 )); fi
    if (( total > 0 )); then
        left=$(( total - $(_project_tokens_total) )); (( left < 0 )) && left=0
        if (( w == 0 || left < w )); then w=$left; fi
    fi
    printf '%s' "$w"
}

# Seconds the next wake must at least wait in project mode (0 = no floor):
# the budget floor when spent, the rest floor when STATE is blocked or done
# and nothing (ritual, matured default) needs doing.
_project_delay_floor() {  # _project_delay_floor [tokens-this-wake]
    local cap wake_tok="${1:-0}" floor=0
    cap=$(_project_cap_daily)
    [[ "$wake_tok" =~ ^[0-9]+$ ]] || wake_tok=0
    if _project_over_budget; then floor=$(_pj_real_span "${PROJECT_BUDGET_REST:-1800}"); fi
    # Pacing: a wake that cost T tokens waits T/cap of a day, so a mind that is
    # busy around the clock spends the daily cap evenly instead of burning it
    # by noon and sleeping until the window rolls. PROJECT_PACE=0 turns it off.
    if [[ "${PROJECT_PACE:-1}" != 0 ]] && (( cap > 0 )); then
        local pace=$(( wake_tok * 86400 / cap / $(_pj_scale) ))
        (( pace > floor )) && floor=$pace
    fi
    local st; st=$(_project_state)
    # A run past its end with the final report written rests like done.
    [[ "$(_project_phase)" == ended ]] && _project_final_done && st=done
    case "$st" in
        blocked|done)
            # Capture, then match: `_project_signals | grep -q` under pipefail
            # fails when grep exits early and the writer takes SIGPIPE.
            local sig; sig=$(_project_signals)
            if [[ -z "$(_project_due_ritual)" && "$sig" != *"- DEFAULT DUE"* && "$sig" != *"- HUMAN ANSWER"* ]]; then
                local rest; rest=$(_pj_real_span "${PROJECT_REST:-3600}")
                (( floor < rest )) && floor=$rest
            fi ;;
        *)
            # An active mind whose last wakes changed nothing waits too,
            # unless something is due that it should act on at once.
            local idle; idle=$(_project_idle_floor)
            if (( idle > floor )); then
                local sig; sig=$(_project_signals)
                if [[ -z "$(_project_due_ritual)" && "$sig" != *"- DEFAULT DUE"* && "$sig" != *"- HUMAN ANSWER"* ]]; then
                    floor=$idle
                fi
            fi ;;
    esac
    printf '%s' "$floor"
}

# Idle wakes. A wake that ran tools but changed no project work file (only
# STATE, librarian.md or questions-summary.md, which every rest touches) is a
# rest, however many commands it ran. Any tool call counts as visible work for
# the backoff, so spontaneous rests came back to back at next delay 0: about 50
# paid wakes an hour on the second live run once the mind ran out of unparked
# work. The step counts such wakes in run/project_idle_streak; the streak floors
# the next delay and, from PROJECT_IDLE_NUDGE on, adds an IDLE signal that
# points at the free blocked rest.
_PJ_IDLE_IGNORE=" STATE librarian.md questions-summary.md "
_project_head() { git -C "$(_project_dir)" rev-parse -q --verify HEAD 2>/dev/null || true; }
_project_wake_changed() {  # _project_wake_changed <HEAD before the wake>: 0 if a work file changed
    local d before="${1:-}" files f
    d=$(_project_dir)
    [[ -d "$d/.git" ]] || return 0
    files=$(git -C "$d" status --porcelain -uall 2>/dev/null | cut -c4-) || files=""
    if [[ -n "$before" ]]; then
        files+=$'\n'$(git -C "$d" diff --name-only "$before" HEAD 2>/dev/null) || true
    fi
    while IFS= read -r f; do
        f=${f##* -> }; f=${f#\"}; f=${f%\"}
        [[ -z "$f" || "$_PJ_IDLE_IGNORE" == *" $f "* ]] && continue
        return 0
    done <<< "$files"
    return 1
}
_project_idle_streak() {
    local n; n=$(cat "$IDENTITY_DIR/run/project_idle_streak" 2>/dev/null) || n=0
    [[ "$n" =~ ^[0-9]+$ ]] || n=0
    printf '%s' "$n"
}
_project_note_wake() {  # _project_note_wake idle|work
    local n=0
    [[ "${1:-}" == idle ]] && n=$(( $(_project_idle_streak) + 1 ))
    mkdir -p "$IDENTITY_DIR/run" 2>/dev/null && printf '%s' "$n" > "$IDENTITY_DIR/run/project_idle_streak" 2>/dev/null || true
}
# Delay after the latest idle wake: PROJECT_IDLE_FLOOR project seconds (600),
# doubling with each further idle wake up to PROJECT_IDLE_CAP (1800). 0 = off.
_project_idle_floor() {
    local n base="${PROJECT_IDLE_FLOOR:-600}" cap="${PROJECT_IDLE_CAP:-1800}" d i=1
    n=$(_project_idle_streak)
    [[ "$base" =~ ^[0-9]+$ && "$cap" =~ ^[0-9]+$ ]] && (( base > 0 && n > 0 )) || { printf 0; return 0; }
    d=$base
    while (( i < n && d < cap )); do d=$(( d * 2 )); i=$(( i + 1 )); done
    (( d > cap )) && d=$cap
    _pj_real_span "$d"
}

# Should this timer wake skip the model entirely? Resting must be free: a
# blocked or done mind that wakes once a project hour only to idle spends a
# model call each time (the first live run's finished mind did). Skip when
# STATE is blocked or done and nothing is due (no ritual, matured default or
# human answer). A blocked mind still gets one real wake per
# PROJECT_REST_CHECK project seconds (default a day) to look for a new way
# forward; a run past its end with its final report gets none. $1 = wake
# mode: a reactive wake (someone wrote to the mind) always runs.
_project_should_skip_rest() {
    [[ "${1:-}" == reactive ]] && return 1
    local st; st=$(_project_state)
    [[ "$(_project_phase)" == ended ]] && _project_final_done && st=done-final
    case "$st" in blocked|done|done-final) ;; *) return 1 ;; esac
    [[ -n "$(_project_due_ritual)" ]] && return 1
    local sig; sig=$(_project_signals)
    [[ "$sig" == *"- DEFAULT DUE"* || "$sig" == *"- HUMAN ANSWER"* ]] && return 1
    [[ "$st" == done-final ]] && return 0
    local f="$IDENTITY_DIR/run/project_rest_checked" last now
    now=$(_pj_now); last=$(cat "$f" 2>/dev/null) || last=0
    [[ "$last" =~ ^[0-9]+$ ]] || last=0
    if (( now - last >= ${PROJECT_REST_CHECK:-86400} )); then
        printf '%s' "$now" > "$f" 2>/dev/null || true
        return 1
    fi
    return 0
}

# Idle rest without a model call. An active mind that has run out of work
# still paid for every wake that found nothing to do: on run A 495 model wakes
# concluded "Rest" and cost $142, because the rest skip above only covers
# STATE blocked or done, and the mind seldom set it. So from
# PROJECT_IDLE_SKIP_STREAK idle wakes in a row (default 3; 0 = off) a timer
# wake skips the model too, unless something could have changed the picture
# since the last wake that ran it ("the last real wake"):
#   - a ritual, a matured default or a human answer is due;
#   - project/spec.md changed (a new brief);
#   - any file under project/ is newer than the last real wake, or the
#     project history moved past its commit: an edit between wakes, or output
#     from a background job the mind started (the runtime does not track the
#     mind's jobs, so their output is the evidence; a job that writes nowhere
#     under project/ is not seen);
#   - the last real wake was PROJECT_IDLE_SKIP_MAX project seconds ago or more
#     (default 3600), so an idle mind still looks around once an hour.
# The record, run/project_last_real_wake, holds "<project epoch> <HEAD> <spec
# checksum>"; its mtime marks when that wake ended. No record: the wake runs.
# $1 = wake mode: a reactive wake (someone wrote to the mind) always runs.
_PJ_LAST_REAL="project_last_real_wake"
_pj_spec_sum() { cksum < "$(_project_dir)/spec.md" 2>/dev/null | awk '{print $1 "-" $2}'; }
_project_note_real_wake() {
    mkdir -p "$IDENTITY_DIR/run" 2>/dev/null || return 0
    printf '%s %s %s\n' "$(_pj_now)" "$(_project_head)" "$(_pj_spec_sum)" > "$IDENTITY_DIR/run/$_PJ_LAST_REAL" 2>/dev/null || true
    return 0
}
# Files under project/ changed after the last real wake ended (the record's
# mtime), the runtime's own between-wake files aside. Prints the first one.
_project_newer_than_real_wake() {
    local d rec f rel
    d=$(_project_dir); rec="$IDENTITY_DIR/run/$_PJ_LAST_REAL"
    while IFS= read -r f; do
        rel="${f#"$d"/}"
        [[ "$_PJ_IDLE_IGNORE" == *" $rel "* ]] && continue
        printf '%s\n' "$rel"; return 0
    done < <(find "$d" -path "$d/.git" -prune -o -type f -newer "$rec" -print 2>/dev/null)
    return 0
}
_project_should_skip_idle() {
    [[ "${1:-}" == reactive ]] && return 1
    [[ "$(_project_state)" == active ]] || return 1
    local min="${PROJECT_IDLE_SKIP_STREAK:-3}"
    [[ "$min" =~ ^[0-9]+$ ]] && (( min > 0 )) || return 1
    (( $(_project_idle_streak) >= min )) || return 1
    [[ -n "$(_project_due_ritual)" ]] && return 1
    local sig; sig=$(_project_signals)
    [[ "$sig" == *"- DEFAULT DUE"* || "$sig" == *"- HUMAN ANSWER"* ]] && return 1
    local rec="$IDENTITY_DIR/run/$_PJ_LAST_REAL" at head spec
    [[ -f "$rec" ]] || return 1
    read -r at head spec < "$rec" || return 1
    [[ "$at" =~ ^[0-9]+$ && -n "$head" ]] || return 1
    (( $(_pj_now) - at < ${PROJECT_IDLE_SKIP_MAX:-3600} )) || return 1
    [[ "$(_pj_spec_sum)" == "$spec" ]] || return 1
    [[ -z "$(_project_newer_than_real_wake)" ]] || return 1
    git -C "$(_project_dir)" cat-file -e "$head^{commit}" 2>/dev/null || return 1
    _project_wake_changed "$head" && return 1
    return 0
}

# Commit project/ if anything changed. $1 = message (the run's FINAL).
_project_commit() {
    local d msg
    d=$(_project_dir); msg="${1:-wake}"
    command -v git >/dev/null 2>&1 || return 0
    [[ -d "$d/.git" ]] || git -C "$d" init -q 2>/dev/null || return 0
    [[ -n "$(git -C "$d" status --porcelain 2>/dev/null)" ]] || return 0
    git -C "$d" add -A >/dev/null 2>&1 || return 0
    git -C "$d" -c user.name="${IDENTITY_NAME:-librarian}" -c user.email="${IDENTITY_NAME:-librarian}@librarian.local" \
        commit -q -m "$(printf '%s' "$msg" | head -c 2000)" >/dev/null 2>&1 || true
    return 0
}
