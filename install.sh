#!/usr/bin/env bash
set -euo pipefail

# install.sh — install Shelly's tools onto PATH.
#
# Two ways in:
#
#   From a checkout:
#     ./install.sh [options]
#
#   One-liner (no checkout needed):
#     curl -fsSL https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh | bash
#
# The one-liner clones the repo to ~/.shelly/app (or a pre-existing
# ~/.shellm), symlink-installs the tools,
# then hands off to `shelly-init` to bootstrap a first identity and start the
# local dash. Pass args through the pipe with `| bash -s -- <args>`.
#
# Prefer to read before you run? Same thing, two steps:
#     curl -fsSLO https://raw.githubusercontent.com/laude-institute/shelly/main/install.sh
#     less install.sh && bash install.sh --init
#
# Everything side-effectful happens inside main(), invoked on the LAST line of
# this file — so a partially downloaded script (a dropped connection mid
# `curl | bash`) parses but executes nothing. Keep it that way: top level is
# only defaults, function definitions, and that final call.

# New SHELLY_* env names win; legacy SHELLM_* spellings still honored.
# State home: SHELLY_HOME/SHELLM_HOME if set; else ~/.shelly, falling back
# to a pre-rename ~/.shellm when only that exists.
SHELLM_REPO="${SHELLY_REPO:-${SHELLM_REPO:-https://github.com/laude-institute/shelly.git}}"
SHELLM_BRANCH="${SHELLY_BRANCH:-${SHELLM_BRANCH:-main}}"
_default_home="$HOME/.shelly"
[ ! -d "$_default_home" ] && [ -d "$HOME/.shellm" ] && _default_home="$HOME/.shellm"
SHELLM_HOME="${SHELLY_HOME:-${SHELLM_HOME:-$_default_home}}"

PREFIX="${PREFIX:-$HOME/.local/bin}"
SYMLINKS="${SYMLINKS:-0}"
RUN_INIT=0
TOOLS=(shellm shellm-docker shellm-docker-broker skills mem llm shellm-explore context traj identity thinkers chat focus recap shelly-init persona)

# ---------------------------------------------------------------------------
# Dependency checks (shared by both modes)
# ---------------------------------------------------------------------------

_pkg_hint() {
    local pkg="$1"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        printf 'brew install %s' "$pkg"
    elif command -v apt-get >/dev/null 2>&1; then
        printf 'sudo apt-get install -y %s' "$pkg"
    elif command -v dnf >/dev/null 2>&1; then
        printf 'sudo dnf install -y %s' "$pkg"
    else
        printf 'install %s with your package manager' "$pkg"
    fi
}

_require_deps() {
    local missing=() failed=0 dep
    for dep in "$@"; do
        command -v "$dep" >/dev/null 2>&1 || missing+=("$dep")
    done
    [[ "${#missing[@]}" -eq 0 ]] && return 0

    # Already root with apt available — a fresh container, typically — so
    # just install them. Still no sudo anywhere: as a normal user we only
    # print the hints below.
    if [[ "$(id -u)" -eq 0 ]] && command -v apt-get >/dev/null 2>&1; then
        echo "==> Installing missing dependencies: ${missing[*]}"
        apt-get update -qq >/dev/null && \
            DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ca-certificates "${missing[@]}" >/dev/null || true
    fi

    for dep in "${missing[@]}"; do
        command -v "$dep" >/dev/null 2>&1 && continue
        printf 'install.sh: missing dependency: %s   (%s)\n' "$dep" "$(_pkg_hint "$dep")" >&2
        failed=1
    done
    [[ "$failed" -eq 0 ]] || exit 1
}

# ---------------------------------------------------------------------------
# Bootstrap mode: no checkout next to this script (i.e. `curl ... | bash`).
# Fetch the repo, then re-exec the checkout's own installer with --init.
# ---------------------------------------------------------------------------

_bootstrap_and_reexec() {
    _require_deps git curl jq

    local app_dir="$SHELLM_HOME/app"
    if [[ -d "$app_dir/.git" ]]; then
        echo "==> Updating existing checkout at $app_dir"
        if ! git -C "$app_dir" pull --ff-only origin "$SHELLM_BRANCH"; then
            echo "install.sh: warning: could not update $app_dir; installing from what's there" >&2
        fi
    else
        echo "==> Cloning $SHELLM_REPO ($SHELLM_BRANCH) to $app_dir"
        mkdir -p "$SHELLM_HOME"
        git clone --branch "$SHELLM_BRANCH" "$SHELLM_REPO" "$app_dir"
    fi
    exec bash "$app_dir/install.sh" --symlinks --init "$@"
}

# ---------------------------------------------------------------------------
# Checkout-mode pieces
# ---------------------------------------------------------------------------

_usage() {
    cat <<'EOF'
Usage: ./install.sh [options]

Installs Shelly's tools from bin/ to a directory on your PATH.

Options:
  --prefix DIR   Install directory (default: ~/.local/bin)
  --symlinks     Create symlinks instead of copies (edits take effect without reinstalling)
  --init         After installing, run `shelly-init` to bootstrap a first
                 identity and start the local dash (the curl|bash one-liner
                 does this by default)
  -h, --help     Show this help

Environment variables:
  PREFIX         Same as --prefix
  SYMLINKS=1     Same as --symlinks
  SHELLY_HOME    Shelly state directory (default: ~/.shelly, or ~/.shellm
                 when only that exists; legacy SHELLM_HOME also honored)

Examples:
  ./install.sh                          # copy to ~/.local/bin
  ./install.sh --symlinks               # symlink to ~/.local/bin
  ./install.sh --prefix /usr/local/bin  # copy to /usr/local/bin (may need sudo)
  PREFIX=~/bin SYMLINKS=1 ./install.sh  # symlink to ~/bin
EOF
}

_install_tools() {
    local tool
    for tool in "${TOOLS[@]}"; do
        if [[ "$SYMLINKS" -eq 1 ]]; then
            ln -sf "$(pwd)/bin/$tool" "$PREFIX/$tool"
            echo "Linked $tool → $PREFIX/$tool"
        else
            cp "bin/$tool" "$PREFIX/$tool"
            chmod +x "$PREFIX/$tool"
            echo "Installed $tool → $PREFIX/$tool"
        fi
    done
}

_install_tui() {
    [[ -d "tui" ]] || return 0
    if ! command -v cargo &>/dev/null; then
        echo "Warning: cargo not found, skipping TUI tools" >&2
        return 0
    fi
    local tui_dir name local_bin
    for tui_dir in tui/*/; do
        [[ -f "${tui_dir}Cargo.toml" ]] || continue
        name=$(basename "$tui_dir")
        printf 'Building %s...\n' "$name"
        (cd "$tui_dir" && cargo build --release --quiet) || {
            printf 'Warning: failed to build %s (skipping)\n' "$name" >&2
            continue
        }
        local_bin="${tui_dir}target/release/$name-tui"
        [[ -f "$local_bin" ]] || local_bin="${tui_dir}target/release/$name"
        if [[ -f "$local_bin" ]]; then
            cp "$local_bin" "$PREFIX/$(basename "$local_bin")"
            codesign --force --sign - "$PREFIX/$(basename "$local_bin")" 2>/dev/null || true
            echo "Installed $(basename "$local_bin") → $PREFIX/$(basename "$local_bin")"
        fi
    done
}

_install_skills() {
    local skills_prefix="${HOME}/.skills/core-skills"
    mkdir -p "$skills_prefix"
    local skill_dir name
    for skill_dir in skills/*/; do
        [[ -f "${skill_dir}SKILL.md" ]] || continue
        name=$(basename "$skill_dir")
        if [[ "$SYMLINKS" -eq 1 ]]; then
            ln -sfn "$(pwd)/$skill_dir" "$skills_prefix/$name"
        else
            rm -rf "${skills_prefix:?}/$name"
            cp -R "$skill_dir" "$skills_prefix/$name"
        fi
    done
    echo "Installed core skills → $skills_prefix"
}

_install_thinkers() {
    [[ -d "thinkers" ]] || return 0
    local thinkers_prefix="${HOME}/.shellm-thinkers"
    mkdir -p "$thinkers_prefix"
    local td name
    if [[ "$SYMLINKS" -eq 1 ]]; then
        for td in thinkers/*/; do
            [[ -d "$td" ]] || continue
            ln -sfn "$(pwd)/$td" "$thinkers_prefix/$(basename "$td")"
        done
        touch "$thinkers_prefix/.use-symlinks"
    else
        for td in thinkers/*/; do
            [[ -d "$td" ]] || continue
            name=$(basename "$td")
            rm -rf "${thinkers_prefix:?}/$name"
            cp -R "$td" "$thinkers_prefix/$name"
        done
        rm -f "$thinkers_prefix/.use-symlinks"
    fi
    # Prune catalog entries for thinkers no longer in the repo, so a thinker
    # that was deleted from thinkers/ doesn't linger here (as a dangling
    # symlink or stale copy) and get resurrected into identities on the next
    # bootstrap. -e || -L catches both live entries and dangling symlinks.
    local entry
    for entry in "$thinkers_prefix"/*; do
        [[ -e "$entry" || -L "$entry" ]] || continue
        name=$(basename "$entry")
        if [[ ! -d "thinkers/$name" ]]; then
            rm -rf "${thinkers_prefix:?}/$name"
            echo "Pruned stale thinker template → $name"
        fi
    done
    echo "Installed thinker templates → $thinkers_prefix"
}

# PATH: make sure the tools are reachable — for this process (so --init can
# chain into shelly-init) and, with consent, for future shells.
# A same-named system binary in a dir BEFORE $PREFIX silently shadows the tool
# we just installed (macOS ships /usr/sbin/chat, /usr/bin/view). Verify each
# installed tool actually resolves to OUR copy; warn if not. Install still
# succeeded — PATH order is the user's to fix — so this warns, never fails.
_warn_shadowed() {
    local tool resolved shadowed=()
    for tool in "${TOOLS[@]}"; do
        [[ -x "$PREFIX/$tool" ]] || continue
        resolved=$(command -v "$tool" 2>/dev/null) || resolved=""
        if [[ -n "$resolved" ]] \
           && [[ "$(realpath "$resolved" 2>/dev/null)" != "$(realpath "$PREFIX/$tool" 2>/dev/null)" ]]; then
            shadowed+=("$tool → $resolved")
        fi
    done
    [[ "${#shadowed[@]}" -eq 0 ]] && return 0
    echo
    echo "Warning: $PREFIX is on your PATH but behind a dir with same-named"
    echo "binaries, so these tools are shadowed by other programs:"
    printf '  %s\n' "${shadowed[@]}"
    echo "Move $PREFIX ahead of the system dirs (e.g. /usr/sbin) in your shell rc:"
    echo "  export PATH=\"$PREFIX:\$PATH\""
}

_ensure_path() {
    case ":$PATH:" in
        *":$PREFIX:"*) _warn_shadowed; return 0 ;;
    esac
    export PATH="$PREFIX:$PATH"
    local path_line="export PATH=\"$PREFIX:\$PATH\"" rc="" reply=""
    case "$(basename "${SHELL:-}")" in
        zsh)  rc="$HOME/.zshrc" ;;
        bash) rc="$HOME/.bashrc" ;;
    esac
    # In a container (throwaway env), don't ask — just persist the PATH.
    local in_container=0
    [[ -f /.dockerenv || -f /run/.containerenv ]] && in_container=1
    if [[ -n "$rc" && "$in_container" -eq 1 ]]; then
        grep -qxF "$path_line" "$rc" 2>/dev/null || printf '\n%s\n' "$path_line" >> "$rc"
        echo "Added $PREFIX to PATH in $rc (container — no prompt)."
    elif [[ -n "$rc" ]] && (: </dev/tty) 2>/dev/null; then
        printf 'Add %s to your PATH in %s? [Y/n] ' "$PREFIX" "$rc" >/dev/tty
        IFS= read -r reply </dev/tty || true
        if [[ ! "$reply" =~ ^[Nn] ]]; then
            grep -qxF "$path_line" "$rc" 2>/dev/null || printf '\n%s\n' "$path_line" >> "$rc"
            echo "Added to $rc (takes effect in new shells)."
        fi
    else
        echo
        echo "Warning: $PREFIX is not on your PATH."
        echo "Add this line to your shell rc (~/.zshrc, ~/.bashrc, etc.):"
        echo "  $path_line"
    fi
}

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

main() {
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd)"
    if [[ ! -f "$script_dir/bin/shellm" ]]; then
        _bootstrap_and_reexec "$@"
    fi
    cd "$script_dir"

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --symlinks) SYMLINKS=1; shift ;;
            --prefix)   PREFIX="${2:?--prefix requires a path}"; shift 2 ;;
            --init)     RUN_INIT=1; shift ;;
            --no-init)  RUN_INIT=0; shift ;;
            --help|-h)  _usage; exit 0 ;;
            *) echo "Unknown option: $1 (try --help)" >&2; exit 1 ;;
        esac
    done

    _require_deps jq curl

    mkdir -p "$PREFIX"
    _install_tools

    # Record where the checkout lives so tools installed as copies (not
    # symlinks) can still find repo assets (web/, identities/, thinkers/).
    mkdir -p "$SHELLM_HOME"
    printf '%s\n' "$(pwd)" > "$SHELLM_HOME/app_dir"

    _install_tui
    _install_skills
    _install_thinkers
    _ensure_path

    if [[ "$RUN_INIT" -eq 1 ]]; then
        echo
        exec "$PREFIX/shelly-init"
    fi
}

main "$@"
