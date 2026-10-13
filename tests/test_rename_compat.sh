#!/usr/bin/env bash
# tests/test_rename_compat.sh — the Headlong → Librarian rename keeps the old
# spellings working (design/rename-to-librarian.md): HEADLONG_* env vars reach
# the tools as LIBRARIAN_* (with the two renamed exceptions), the headlong-*
# command names run the librarian-* tools, the state home and thinker
# templates fall back to an existing ~/.headlong* directory, the Python
# packages keep their old console-script aliases, and every entry script
# sources the mapping. No LLM calls, no docker.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; REPO="$(dirname "$HERE")"
pass=0; fail=0
ok()  { pass=$((pass+1)); printf 'ok   %s\n' "$1"; }
bad() { fail=$((fail+1)); printf 'FAIL %s%s\n' "$1" "${2:+ — $2}"; }
eq() { if [[ "$2" == "$3" ]]; then ok "$1"; else bad "$1" "got '$2', want '$3'"; fi; }
has() { if printf '%s' "$2" | grep -F -- "$3" >/dev/null; then ok "$1"; else bad "$1" "missing '$3' in: $(printf '%s' "$2" | head -c 300)"; fi; }

WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

# ── the mapping itself ───────────────────────────────────────────────────────
out=$(env -i HOME="$WORK" PATH="$PATH" HEADLONG_HOME=/x/home HEADLONG_LIBRARIAN=0 HEADLONG_LIBRARIAN_SRC=/x/src HEADLONG_TZ=UTC LIBRARIAN_TZ=Europe/Oslo \
    bash -c '. "$1"; printf "%s|%s|%s|%s|%s\n" "$LIBRARIAN_HOME" "$LIBRARIAN_MEMORY" "$LIBRARIAN_SRC" "$LIBRARIAN_TZ" "${LIBRARIAN_LIBRARIAN:-unset}"' _ "$REPO/bin/librarian-env")
eq "HEADLONG_HOME maps to LIBRARIAN_HOME" "${out%%|*}" /x/home
rest="${out#*|}"; eq "HEADLONG_LIBRARIAN maps to LIBRARIAN_MEMORY" "${rest%%|*}" 0
rest="${rest#*|}"; eq "HEADLONG_LIBRARIAN_SRC maps to LIBRARIAN_SRC" "${rest%%|*}" /x/src
rest="${rest#*|}"; eq "an explicit LIBRARIAN_* value wins" "${rest%%|*}" Europe/Oslo
eq "no LIBRARIAN_LIBRARIAN is invented" "${rest#*|}" unset

# ── state-home and templates fallback ────────────────────────────────────────
mkdir -p "$WORK/h1/.headlong" "$WORK/h1/.headlong-thinkers"
out=$(env -i HOME="$WORK/h1" PATH="$PATH" bash -c '. "$1"; printf "%s|%s" "${LIBRARIAN_HOME:-}" "${LIBRARIAN_THINKERS_TEMPLATES:-}"' _ "$REPO/bin/librarian-env")
eq "an existing ~/.headlong becomes the state home" "${out%%|*}" "$WORK/h1/.headlong"
eq "an existing ~/.headlong-thinkers becomes the templates dir" "${out#*|}" "$WORK/h1/.headlong-thinkers"
mkdir -p "$WORK/h2/.headlong" "$WORK/h2/.librarian"
out=$(env -i HOME="$WORK/h2" PATH="$PATH" bash -c '. "$1"; printf "%s" "${LIBRARIAN_HOME:-}"' _ "$REPO/bin/librarian-env")
eq "with both dirs present nothing is forced (the default ~/.librarian applies)" "$out" ""
out=$(env -i HOME="$WORK/h3" PATH="$PATH" bash -c 'set -u; . "$1" && echo fine' _ "$REPO/bin/librarian-env")
eq "the mapping is set -u safe with no legacy vars" "$out" fine

# ── old command names run the new tools ─────────────────────────────────────
for t in init killall project skills web slack-bridge telegram-bridge; do
    [[ -L "$REPO/tools/headlong-$t" && "$(readlink "$REPO/tools/headlong-$t")" == "librarian-$t" ]] && ok "tools/headlong-$t links to librarian-$t" || bad "tools/headlong-$t links to librarian-$t"
done
[[ -L "$REPO/deploy/headlong-thinkersctl" ]] && ok "deploy/headlong-thinkersctl is an alias" || bad "deploy/headlong-thinkersctl is an alias"
out=$("$REPO/tools/headlong-project" 2>&1 || true)
has "headlong-project prints librarian-project's usage" "$out" "librarian-project"
has "install.sh installs the legacy names" "$(grep -E '^LEGACY_TOOLS=' "$REPO/install.sh")" "headlong-init"
has "install.sh installs the memory tool and the mapping" "$(grep -E '^(AUX|BIN)_TOOLS=' "$REPO/install.sh")" "librarian-env"
has "install.sh recognizes Headlong copies it may replace" "$(grep -n "_is_librarian_copy()" -A4 "$REPO/install.sh")" "headlong"

# ── every entry script sources the mapping ──────────────────────────────────
for s in tools/librarian-init tools/librarian-web tools/librarian-project tools/librarian-slack-bridge tools/librarian-telegram-bridge tools/persona tools/identity tools/librarian \
         bin/thinkers bin/shellm bin/llm bin/blind status.sh uninstall.sh thinkers/_lib/common.sh thinkers/monolith/step; do
    grep -q "librarian-env" "$REPO/$s" && ok "$s sources librarian-env" || bad "$s sources librarian-env"
done
for s in install.sh deploy/update.sh deploy/setup.sh deploy/migrate-units.sh deploy/thinkers-silence-alert.sh; do
    grep -q "compgen -A variable HEADLONG_" "$REPO/$s" && ok "$s inlines the mapping" || bad "$s inlines the mapping"
done

# ── a tool honors HEADLONG_HOME end to end ───────────────────────────────────
mkdir -p "$WORK/sh/.local/bin"
out=$(env -i HOME="$WORK/sh" PATH="$REPO/bin:$REPO/tools:$PATH" HEADLONG_HOME="$WORK/statehome" bash -c 'cd "$1" && bash status.sh 2>&1 | head -40' _ "$REPO" || true)
has "status.sh reports the Headlong-era state home" "$out" "$WORK/statehome"

# ── python packages keep their old script names ──────────────────────────────
has "headlong-web alias" "$(cat "$REPO/web/pyproject.toml")" 'headlong-web = "librarian_web.cli:main"'
has "headlong-slack-bridge alias" "$(cat "$REPO/slack/pyproject.toml")" 'headlong-slack-bridge = "librarian_slack.cli:main"'
has "headlong-telegram-bridge alias" "$(cat "$REPO/telegram/pyproject.toml")" 'headlong-telegram-bridge = "librarian_telegram.cli:main"'
out=$(cd "$REPO/web/src" && HEADLONG_WEB_URL=http://old LIBRARIAN_X=1 python3 -c 'from librarian_web.env import getenv; print(getenv("LIBRARIAN_WEB_URL"), getenv("LIBRARIAN_MEMORY", "d"))' 2>&1)
eq "env.py falls back to HEADLONG_ names" "$out" "http://old d"
out=$(cd "$REPO/web/src" && HEADLONG_LIBRARIAN=0 python3 -c 'from librarian_web.env import getenv; print(getenv("LIBRARIAN_MEMORY"))' 2>&1)
eq "env.py maps the renamed memory switch" "$out" "0"

# ── deploy compat ────────────────────────────────────────────────────────────
has "migrate-units migrates headlong-* units" "$(grep -c 'headlong-.*:librarian-' "$REPO/deploy/migrate-units.sh")" "8"
has "update.sh refuses with headlong-* units installed" "$(grep legacy_units= "$REPO/deploy/update.sh")" "headlong"
has "sudoers permits both wrappers" "$(cat "$REPO/deploy/sudoers-librarian-thinkers")" "headlong-thinkersctl"
has "the cgroup guard matches both unit names" "$(grep -n 'thinkers@\${esc}.service' "$REPO/bin/thinkers")" "headlong-thinkers@"

printf '\n%d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
