#!/usr/bin/env bash
set -uo pipefail

# status.sh — what Headlong has on this machine, and what is running.
#
#   curl -fsSL https://headlong.ai/status.sh | bash
#   ./status.sh                 (from a checkout)
#
# Read-only: prints and exits. No prompts, nothing changed, no network. Use
# it to see what `ada stop`, `headlong-killall` or uninstall.sh would act on,
# or paste its output into a bug report. Needs only bash and ps.

HEADLONG_HOME="${HEADLONG_HOME:-$HOME/.headlong}"
PREFIX="${PREFIX:-$HOME/.local/bin}"
TOOLS=(shellm shellm-docker skills mem llm context traj thinkers chat focus recap glob view put sub
       shellm-docker-broker identity shellm-explore headlong-init headlong-killall persona headlong-web
       headlong-slack-bridge headlong-telegram-bridge headlong-tui)
# Process shapes, same as headlong-killall (the source of truth) and
# uninstall.sh; tests/test_uninstall.sh checks the three agree.
PATTERNS=(
    'bash [^ ]*/(bin|tools)/(shellm|shellm-explore|llm|chat|sub)( |$)'
    'bash [^ ]*/bin/thinkers( |$)'
    'bash [^ ]*/thinkers/[^ /]+/step( |$)'
    'bash [^ ]*/bin/traj tail'
    'tail -n 0 -F [^ ]*trajectory\.jsonl'
)
DASH_PAT='(uv run --project [^ ]+ |/\.venv/bin/)(headlong|shellm|shelly)-web( |$)'

say()   { printf '%s\n' "$*"; }
head_() { printf '\n==> %s\n' "$*"; }
alive() { [[ -n "${1:-}" ]] && kill -0 "$1" 2>/dev/null; }

case "${1:-}" in
    -h|--help) sed -n '4,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    "") ;;
    *) echo "status.sh takes no options (try --help)" >&2; exit 1 ;;
esac

# --- install ------------------------------------------------------------------
APP_DIR=""
recorded=$(cat "$HEADLONG_HOME/app_dir" 2>/dev/null || true)
if [[ -n "$recorded" && -f "$recorded/bin/shellm" ]]; then APP_DIR="$recorded"
elif [[ -f "$HEADLONG_HOME/app/bin/shellm" ]]; then APP_DIR="$HEADLONG_HOME/app"
else
    here="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
    [[ -f "$here/bin/shellm" ]] && APP_DIR="$here"
fi

say
say "Headlong status — $(date '+%Y-%m-%d %H:%M:%S') on $(hostname 2>/dev/null || uname -n)"
head_ "Install"
if [[ -z "$APP_DIR" && ! -d "$HEADLONG_HOME" ]]; then
    say "  not installed (no $HEADLONG_HOME, no checkout found)"
else
    if [[ -n "$APP_DIR" ]]; then
        commit=$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo "?")
        dirty=$(git -C "$APP_DIR" status --short 2>/dev/null | wc -l | tr -d ' ')
        edits=""; [[ "${dirty:-0}" -gt 0 ]] && edits=", $dirty local edit(s)"
        say "  checkout:   $APP_DIR   (commit $commit$edits)"
    else
        say "  checkout:   not found"
    fi
    if [[ -d "$HEADLONG_HOME" ]]; then
        keys=""
        for k in ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY; do
            grep -q "^$k=" "$HEADLONG_HOME/.env" 2>/dev/null && keys="$keys $k"
        done
        model=$(sed -n 's/^SHELLM_MODEL=//p' "$HEADLONG_HOME/.env" 2>/dev/null | tail -1)
        say "  state home: $HEADLONG_HOME   (.env has:${keys:- no API key}${model:+; model $model})"
    else
        say "  state home: $HEADLONG_HOME   (missing)"
    fi
    n=0; persona_links=""
    for t in "${TOOLS[@]}"; do [[ -e "$PREFIX/$t" || -L "$PREFIX/$t" ]] && n=$((n+1)); done
    for f in "$PREFIX"/*; do
        [[ -L "$f" && "$(readlink "$f")" == */persona && "$(basename "$f")" != persona ]] && persona_links="$persona_links $(basename "$f")"
    done
    say "  tools:      $n of ${#TOOLS[@]} in $PREFIX${persona_links:+; agent commands:$persona_links}"
    case ":$PATH:" in *":$PREFIX:"*) say "  PATH:       $PREFIX is on PATH" ;; *) say "  PATH:       $PREFIX is NOT on PATH in this shell" ;; esac
    [[ -d "$HOME/.skills/core-skills" ]]  && say "  skills:     $HOME/.skills/core-skills"
    [[ -d "$HOME/.headlong-thinkers" ]]   && say "  thinkers:   $HOME/.headlong-thinkers"
fi

# --- identities ---------------------------------------------------------------
if [[ -n "$APP_DIR" && -d "$APP_DIR/.identities" ]]; then
    head_ "Identities  ($APP_DIR/.identities)"
    def=""; [[ -L "$APP_DIR/.identities/default" ]] && def=$(basename "$(readlink "$APP_DIR/.identities/default")")
    found=0
    for d in "$APP_DIR/.identities"/*/; do
        [[ -d "$d" ]] || continue
        name=$(basename "$d"); [[ "$name" == default ]] && continue
        found=1
        pid=$(cat "$d/run/dispatcher.pid" 2>/dev/null || true)
        if alive "$pid"; then mind="mind running (dispatcher pid $pid)"; else mind="mind stopped"; fi
        tj=$(ls -t "$d"/trajectories/*/trajectory.jsonl 2>/dev/null | head -1)
        last=""; [[ -n "$tj" ]] && last=$(tail -1 "$tj" 2>/dev/null | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')
        rows=""; [[ -n "$tj" ]] && rows=$(wc -l <"$tj" | tr -d ' ')
        tag=""; [[ "$name" == "$def" ]] && tag=" (default)"
        say "  $name$tag: $mind${rows:+; $rows trajectory rows}${last:+, last at $last}"
    done
    [[ "$found" -eq 1 ]] || say "  none"
fi

# --- dash ---------------------------------------------------------------------
head_ "Dash"
wpid=$(cat "$HEADLONG_HOME/run/web.pid" 2>/dev/null || true)
if alive "$wpid"; then
    url=$(grep -o 'http://[^ ]*' "$HEADLONG_HOME/logs/web.log" 2>/dev/null | tail -1)
    say "  running (pid $wpid)${url:+ at $url}"
else
    say "  stopped"
fi

# --- processes ----------------------------------------------------------------
head_ "Headlong processes on this machine"
procs=$(
    for pat in "${PATTERNS[@]}" "$DASH_PAT"; do pgrep -fl "$pat" 2>/dev/null || true; done \
        | grep -E '^[0-9]+ ' | grep -v "^$$ " | sort -un -k1,1
)
if [[ -n "$procs" ]]; then
    printf '%s\n' "$procs" | cut -c1-${COLUMNS:-110} | sed 's/^/  /'
    say
    say "  $(printf '%s\n' "$procs" | grep -c '') process(es). Stop one agent: <name> stop   All: headlong-killall --web"
else
    say "  none"
fi
if command -v docker >/dev/null 2>&1; then
    c=$(docker ps --filter 'name=^shellm-' --format '  {{.Names}}  {{.Status}}' 2>/dev/null || true)
    if [[ -n "$c" ]]; then head_ "Docker sandboxes"; printf '%s\n' "$c"; fi
fi

say
say "  Bundle details for a bug report:  <name> bugreport"
say "  Remove everything:                curl -fsSL https://headlong.ai/uninstall.sh | bash"
say
