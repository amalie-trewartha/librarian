#!/usr/bin/env bash
# Librarian names are canonical; Headlong spellings still work (same mapping as bin/librarian-env).
if [[ -z "${LIBRARIAN_MEMORY+x}" && -n "${HEADLONG_LIBRARIAN+x}" ]]; then export LIBRARIAN_MEMORY="$HEADLONG_LIBRARIAN"; fi
if [[ -z "${LIBRARIAN_SRC+x}" && -n "${HEADLONG_LIBRARIAN_SRC+x}" ]]; then export LIBRARIAN_SRC="$HEADLONG_LIBRARIAN_SRC"; fi
for _le_hv in $(compgen -A variable HEADLONG_ 2>/dev/null); do
    case "$_le_hv" in HEADLONG_LIBRARIAN|HEADLONG_LIBRARIAN_SRC) continue ;; esac
    _le_lv="LIBRARIAN_${_le_hv#HEADLONG_}"
    if [[ -z "${!_le_lv+x}" ]]; then export "$_le_lv=${!_le_hv}"; fi
done
unset _le_hv _le_lv
if [[ -z "${LIBRARIAN_HOME:-}" && -n "${HOME:-}" && ! -d "$HOME/.librarian" && -d "$HOME/.headlong" ]]; then
    export LIBRARIAN_HOME="$HOME/.headlong"
fi
if [[ -z "${LIBRARIAN_THINKERS_TEMPLATES:-}" && -n "${HOME:-}" ]]; then
    if [[ ! -d "$HOME/.librarian-thinkers" && -d "$HOME/.headlong-thinkers" ]]; then
        export LIBRARIAN_THINKERS_TEMPLATES="$HOME/.headlong-thinkers"
    fi
fi

set -uo pipefail

# status.sh — what Librarian has on this machine, and what is running.
#
#   curl -fsSL https://raw.githubusercontent.com/amalie-trewartha/librarian/main/status.sh | bash
#   ./status.sh                 (from a checkout)
#
# Read-only: prints and exits. No prompts, nothing changed, no network. Use
# it to see what `ada stop`, `librarian-killall` or uninstall.sh would act on,
# or paste its output into a bug report. Needs only bash and ps.

LIBRARIAN_HOME="${LIBRARIAN_HOME:-$HOME/.librarian}"
PREFIX="${PREFIX:-$HOME/.local/bin}"
ON_PATH=1          # set below; when 0, commands are printed with full paths
BIN=""             # where to find a tool from THIS shell: "" (on PATH),
                   # "$PREFIX/" (installed, off PATH) or "$APP_DIR/tools/"
cmd_for() {        # cmd_for <identity> — how to address it from THIS shell
    if [[ -L "$PREFIX/$1" && "$(readlink "$PREFIX/$1")" == */persona ]]; then printf '%s%s' "$BIN" "$1"
    else printf '%spersona %s' "$BIN" "$1"; fi
}
TOOLS=(shellm shellm-docker skills mem llm context traj thinkers chat recap
       shellm-docker-broker identity shellm-explore librarian-skills librarian-init librarian-killall persona librarian-web
       librarian-slack-bridge librarian-telegram-bridge librarian-tui
       librarian librarian-env headlong-init headlong-killall headlong-project headlong-skills headlong-web headlong-slack-bridge headlong-telegram-bridge)
# Process shapes, same as librarian-killall (the source of truth) and
# uninstall.sh; tests/test_uninstall.sh checks the three agree.
PATTERNS=(
    'bash [^ ]*/(bin|tools)/(shellm|shellm-explore|llm|chat)( |$)'
    'bash [^ ]*/bin/thinkers( |$)'
    'bash [^ ]*/thinkers/[^ /]+/step( |$)'
    'bash [^ ]*/bin/traj tail'
    'tail -n 0 -F [^ ]*trajectory\.jsonl'
)
DASH_PAT='(uv run --project [^ ]+ |/\.venv/bin/)(librarian|shellm|shelly)-web( |$)'

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
recorded=$(cat "$LIBRARIAN_HOME/app_dir" 2>/dev/null || true)
if [[ -n "$recorded" && -f "$recorded/bin/shellm" ]]; then APP_DIR="$recorded"
elif [[ -f "$LIBRARIAN_HOME/app/bin/shellm" ]]; then APP_DIR="$LIBRARIAN_HOME/app"
else
    here="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
    [[ -f "$here/bin/shellm" ]] && APP_DIR="$here"
fi

say
say "Librarian status — $(date '+%Y-%m-%d %H:%M:%S') on $(hostname 2>/dev/null || uname -n)"
head_ "Install"
if [[ -z "$APP_DIR" && ! -d "$LIBRARIAN_HOME" ]]; then
    say "  not installed (no $LIBRARIAN_HOME, no checkout found)"
else
    if [[ -n "$APP_DIR" ]]; then
        commit=$(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo "?")
        dirty=$(git -C "$APP_DIR" status --short 2>/dev/null | wc -l | tr -d ' ')
        edits=""; [[ "${dirty:-0}" -gt 0 ]] && edits=", $dirty local edit(s)"
        say "  checkout:   $APP_DIR   (commit $commit$edits)"
    else
        say "  checkout:   not found"
    fi
    if [[ -d "$LIBRARIAN_HOME" ]]; then
        keys=""
        for k in ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY OPENROUTER_API_KEY; do
            grep -q "^$k=" "$LIBRARIAN_HOME/.env" 2>/dev/null && keys="$keys $k"
        done
        # .env values are single-quoted (librarian-init _env_set); strip a
        # matching pair of surrounding quotes for display.
        model=$(sed -n 's/^SHELLM_MODEL=//p' "$LIBRARIAN_HOME/.env" 2>/dev/null | tail -1)
        model="${model#\'}"; model="${model%\'}"
        say "  state home: $LIBRARIAN_HOME   (.env has:${keys:- no API key}${model:+; model $model})"
    else
        say "  state home: $LIBRARIAN_HOME   (missing)"
    fi
    n=0; persona_links=""
    for t in "${TOOLS[@]}"; do [[ -e "$PREFIX/$t" || -L "$PREFIX/$t" ]] && n=$((n+1)); done
    for f in "$PREFIX"/*; do
        [[ -L "$f" && "$(readlink "$f")" == */persona && "$(basename "$f")" != persona ]] && persona_links="$persona_links $(basename "$f")"
    done
    say "  tools:      $n of ${#TOOLS[@]} in $PREFIX${persona_links:+; agent commands:$persona_links}"
    ON_PATH=0
    case ":$PATH:" in *":$PREFIX:"*) ON_PATH=1; say "  PATH:       $PREFIX is on PATH" ;; *) say "  PATH:       $PREFIX is NOT on PATH in this shell" ;; esac
    if [[ "$ON_PATH" -eq 0 ]]; then
        if [[ -e "$PREFIX/persona" ]]; then BIN="$PREFIX/"
        elif [[ -n "$APP_DIR" && -x "$APP_DIR/tools/persona" ]]; then BIN="$APP_DIR/tools/"; fi
    fi
    [[ -d "$HOME/.skills/core-skills" ]]  && say "  skills:     $HOME/.skills/core-skills"
    [[ -d "${LIBRARIAN_THINKERS_TEMPLATES:-$HOME/.librarian-thinkers}" ]]   && say "  thinkers:   $HOME/.librarian-thinkers"
fi

# --- LLM: last call, from the marker bin/llm keeps --------------------------------
LLM_ALERT=""
hf="$LIBRARIAN_HOME/run/llm_health.json"
if [[ -f "$hf" ]] && [[ "$(jq -r '.ok' "$hf" 2>/dev/null)" == "false" ]]; then
    IFS=$'\t' read -r lk lc lm lt lp < <(jq -r '[(.kind // "other"), (.http_code // "" | tostring), (.message // ""), (.ts // ""), (.provider // "")] | @tsv' "$hf" 2>/dev/null)
    case "$lk" in
        credit) LLM_ALERT="OUT OF CREDIT — the API key has no money left" ;;
        auth)   LLM_ALERT="KEY REJECTED — the API key is invalid or revoked" ;;
        rate)   LLM_ALERT="RATE LIMITED" ;;
        *)      LLM_ALERT="last call failed" ;;
    esac
    head_ "LLM"
    say "  !! $LLM_ALERT (${lp:-provider}${lc:+, HTTP $lc}, last tried $lt)"
    [[ -n "$lm" ]] && say "     provider said: ${lm:0:160}"
    case "$lk" in
        credit) say "     Fix: top up the key (or put a new one in $LIBRARIAN_HOME/.env), then start the agent again." ;;
        auth)   say "     Fix: put a working key in $LIBRARIAN_HOME/.env, then start the agent again." ;;
    esac
elif [[ -f "$hf" ]]; then
    head_ "LLM"
    say "  ok (last call $(jq -r '.ts' "$hf" 2>/dev/null) via $(jq -r '.provider // "?"' "$hf" 2>/dev/null))"
fi

# --- identities ---------------------------------------------------------------
IDS=()
if [[ -n "$APP_DIR" && -d "$APP_DIR/.identities" ]]; then
    head_ "Identities  ($APP_DIR/.identities)"
    def=""; [[ -L "$APP_DIR/.identities/default" ]] && def=$(basename "$(readlink "$APP_DIR/.identities/default")")
    found=0
    for d in "$APP_DIR/.identities"/*/; do
        [[ -d "$d" ]] || continue
        name=$(basename "$d"); [[ "$name" == default ]] && continue
        found=1; IDS+=("$name")
        pid=$(cat "$d/run/dispatcher.pid" 2>/dev/null || true)
        if alive "$pid"; then mind="mind running (dispatcher pid $pid)"; else mind="mind stopped"; fi
        tj=$(ls -t "$d"/trajectories/*/trajectory.jsonl 2>/dev/null | head -1 || true)
        last=""; [[ -n "$tj" ]] && last=$(tail -1 "$tj" 2>/dev/null | sed -n 's/.*"ts":"\([^"]*\)".*/\1/p')
        rows=""; [[ -n "$tj" ]] && rows=$(wc -l <"$tj" | tr -d ' ')
        tag=""; [[ "$name" == "$def" ]] && tag=" (default)"
        say "  $name$tag: $mind${rows:+; $rows trajectory rows}${last:+, last at $last}"
    done
    [[ "$found" -eq 1 ]] || say "  none"
fi

# --- dash ---------------------------------------------------------------------
head_ "Dash"
wpid=$(cat "$LIBRARIAN_HOME/run/web.pid" 2>/dev/null || true)
if alive "$wpid"; then
    url=$(grep -o 'http://[^ ]*' "$LIBRARIAN_HOME/logs/web.log" 2>/dev/null | tail -1)
    say "  running (pid $wpid)${url:+ at $url}"
else
    say "  stopped"
fi

# --- processes ----------------------------------------------------------------
head_ "Librarian processes on this machine"
procs=$(
    for pat in "${PATTERNS[@]}" "$DASH_PAT"; do pgrep -fl "$pat" 2>/dev/null || true; done \
        | grep -E '^[0-9]+ ' | grep -v "^$$ " | sort -un -k1,1
)
if [[ -n "$procs" ]]; then
    printf '%s\n' "$procs" | cut -c1-${COLUMNS:-110} | sed 's/^/  /'
    say
    say "  $(printf '%s\n' "$procs" | grep -c '') process(es)."
else
    say "  none"
fi
if command -v docker >/dev/null 2>&1; then
    c=$(docker ps --filter 'name=^shellm-' --format '  {{.Names}}  {{.Status}}' 2>/dev/null || true)
    if [[ -n "$c" ]]; then head_ "Docker sandboxes"; printf '%s\n' "$c"; fi
fi

# --- commands that work from this shell ---------------------------------------
head_ "Commands (for this shell)"
if [[ "$ON_PATH" -eq 0 && -e "$PREFIX/persona" ]]; then
    say "  $PREFIX is not on PATH here, so these use full paths. To fix:"
    say "    export PATH=\"$PREFIX:\$PATH\""
    say
fi
cmdrow() { printf '  %-20s %s\n' "$1" "$2"; }
# Full rows for the default identity (or the only/first one); the rest on
# one line — same verbs, different name.
main_id=""; others=()
for name in "${IDS[@]+"${IDS[@]}"}"; do
    if [[ -z "$main_id" && ( "$name" == "${def:-}" || -z "${def:-}" ) ]]; then main_id="$name"; else others+=("$name"); fi
done
if [[ -n "$main_id" ]]; then
    c=$(cmd_for "$main_id")
    cmdrow "pause $main_id:"     "$c stop"
    cmdrow "resume $main_id:"    "$c start"
    cmdrow "chat with $main_id:" "$c      (one-shot: $c \"hello there\")"
    cmdrow "bug report bundle:"  "$c bugreport"
    if [[ "${#others[@]}" -gt 0 ]]; then
        cmdrow "other identities:" "${BIN}persona <name> stop|start|bugreport   for: ${others[*]}"
    fi
fi
[[ -x "${BIN:-./}librarian-killall" || -n "$(command -v librarian-killall 2>/dev/null)" || -x "${BIN}librarian-killall" ]] \
    && cmdrow "stop everything:" "${BIN}librarian-killall --web"
cmdrow "uninstall:" "curl -fsSL https://raw.githubusercontent.com/amalie-trewartha/librarian/main/uninstall.sh | bash"
say
