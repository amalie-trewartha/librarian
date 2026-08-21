#!/usr/bin/env bash
set -euo pipefail

# deploy/migrate-units.sh — one-time cutover from the shelly-* systemd units
# to headlong-*. Run once per box, in a window someone is watching:
#
#   sudo bash /opt/shellm/app/deploy/migrate-units.sh --dry-run   # rehearse
#   sudo bash /opt/shellm/app/deploy/migrate-units.sh             # do it
#   sudo bash /opt/shellm/app/deploy/migrate-units.sh --rollback  # undo it
#
# This is deliberately NOT part of deploy/update.sh. Renaming the thinkers
# unit stops the identity dispatchers — a mind restart with a ~3 minute
# drain — and update.sh runs unattended from the dash's self-update button.
# A one-time step that kills the mind must be typed on purpose. update.sh
# refuses to run while legacy units are installed and points here.
#
# Unlike the 2026-08-19 shellm->shelly rename, this cutover ships NO
# back-compat: no legacy console-script aliases, no dual wrapper names, no
# dual-match in the self-stop guard. That means:
#
#   - Between `git pull` + `uv sync` on the rename commit and running this
#     script, the installed shelly-* units point at console scripts that no
#     longer exist, and the cgroup self-stop guard in bin/thinkers does not
#     match the still-running shelly-thinkers@ cgroup. Keep that window
#     short and supervised; run this script immediately after the deploy.
#   - --rollback restores the shelly-* unit files it backed up, but their
#     ExecStart binaries (shelly-web, shelly-slack-bridge, ...) only exist
#     while the code is on a pre-rename commit. A real rollback is:
#     git checkout <pre-rename commit>, uv sync each project, THEN
#     --rollback. The EBS snapshot is the deep backstop.
#
# Writing a migration like this one? deploy/MIGRATIONS.md is the playbook:
# the couplings that fail silently, and the verification checklist.
#
# Out of scope on purpose (these stay "shellm"): the /opt/shellm path, the
# shellm and shellm-telegram UNIX users, ~shellm/.shellm, the per-identity
# .shellm/ subdir, and the *.shellm.net domains. Each is a physical move
# with its own migration; none of them need to happen for the unit rename.

APP_DIR="${APP_DIR:-/opt/shellm/app}"
SHELLM_HOME="${SHELLM_HOME:-$(dirname "$APP_DIR")}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/headlong-unit-migration}"
# Overridable so the script can be rehearsed against a scratch layout.
SYSD="${SYSD:-/etc/systemd/system}"
SUDOERS_D="${SUDOERS_D:-/etc/sudoers.d}"
AUDIT_D="${AUDIT_D:-/etc/audit/rules.d}"
LOCAL_BIN="${LOCAL_BIN:-/usr/local/bin}"

# legacy:new. Order matters for stop (below) but not here.
UNIT_PAIRS=(
    "shelly-web.service:headlong-web.service"
    "shelly-thinkers@.service:headlong-thinkers@.service"
    "shelly-thinkers-alert@.service:headlong-thinkers-alert@.service"
    "shelly-slack-bridge.service:headlong-slack-bridge.service"
    "shelly-slack-agent.service:headlong-slack-agent.service"
    "shelly-telegram-bridge.service:headlong-telegram-bridge.service"
)

# Stopped in this order: bridges first so nothing new arrives while the mind
# drains, then the persona bootstrap, then the dispatchers, then the web
# control plane last (it is what an operator watches for health).
STOP_ORDER=(
    shelly-slack-bridge.service
    shelly-telegram-bridge.service
    shelly-slack-agent.service
    shelly-web.service
)

DRY_RUN=0
MODE=migrate
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --rollback) MODE=rollback ;;
        -h|--help) sed -n '4,10p' "$0"; exit 0 ;;
        *) echo "unknown argument: $arg" >&2; exit 2 ;;
    esac
done

# A dry run only reads and prints, so it does not need root.
if [[ $DRY_RUN -eq 0 && $EUID -ne 0 ]]; then
    echo "error: run as root (sudo bash $0)" >&2
    exit 1
fi

say() { printf '==> %s\n' "$*"; }
run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    [dry-run] %s\n' "$*"
    else
        "$@"
    fi
}

# Running thinkers instances, e.g. "audel" — recorded before the stop so the
# same minds come back up afterwards. The template itself is never enabled;
# instances are started by the slack persona bootstrap (oneshot).
thinker_instances() {
    local prefix="$1" u
    systemctl list-units --all --plain --no-legend "${prefix}@*" 2>/dev/null \
        | awk '{print $1}' \
        | while read -r u; do
            u="${u%.service}"
            printf '%s\n' "${u#*@}"
        done
}

########################################################################
# Rollback
########################################################################
if [[ "$MODE" == rollback ]]; then
    [[ -d "$BACKUP_DIR" ]] || { echo "error: no backup at $BACKUP_DIR" >&2; exit 1; }
    say "Rolling back to the shelly-* units from $BACKUP_DIR"
    echo "    NOTE: the restored units exec shelly-* console scripts, which" >&2
    echo "    only exist while the code is on a pre-rename commit. Revert the" >&2
    echo "    checkout and uv sync BEFORE this, or the units will not start." >&2

    # Stop the minds first — same reason as the forward path, and a running
    # dispatcher in a cgroup whose unit file is about to vanish is a mess.
    while read -r ident; do
        [[ -n "$ident" ]] || continue
        say "Stopping headlong-thinkers@$ident"
        run systemctl stop "headlong-thinkers@$ident.service" || true
    done < <(thinker_instances headlong-thinkers)

    for pair in "${UNIT_PAIRS[@]}"; do
        new="${pair#*:}"
        [[ -f "$SYSD/$new" ]] || continue
        run systemctl disable --now "$new" || true
        run rm -f "$SYSD/$new"
    done
    if [[ -d "$SYSD/headlong-web.service.d" ]]; then
        run rm -rf "$SYSD/headlong-web.service.d"
    fi

    for pair in "${UNIT_PAIRS[@]}"; do
        legacy="${pair%%:*}"
        [[ -f "$BACKUP_DIR/units/$legacy" ]] || continue
        run install -o root -g root -m 0644 "$BACKUP_DIR/units/$legacy" "$SYSD/$legacy"
    done
    if [[ -d "$BACKUP_DIR/units/shelly-web.service.d" ]]; then
        run cp -a "$BACKUP_DIR/units/shelly-web.service.d" "$SYSD/"
    fi

    if [[ -f "$BACKUP_DIR/shelly-thinkersctl" ]]; then
        run install -o root -g root -m 0755 "$BACKUP_DIR/shelly-thinkersctl" $LOCAL_BIN/shelly-thinkersctl
    fi
    if [[ -f "$BACKUP_DIR/sudoers-shelly-thinkers" ]]; then
        run install -o root -g root -m 0440 "$BACKUP_DIR/sudoers-shelly-thinkers" $SUDOERS_D/shelly-thinkers
    fi
    run rm -f $SUDOERS_D/headlong-thinkers $LOCAL_BIN/headlong-thinkersctl
    if [[ -f "$BACKUP_DIR/shelly-signals.rules" ]]; then
        run install -o root -g root -m 0640 "$BACKUP_DIR/shelly-signals.rules" $AUDIT_D/shelly-signals.rules
    fi
    run rm -f $AUDIT_D/headlong-signals.rules

    run systemctl daemon-reload

    # Restore the enabled/active state recorded at migration time.
    while IFS=$'\t' read -r unit enabled active; do
        [[ -n "$unit" ]] || continue
        # Templates have no state of their own — enabling or starting a bare
        # foo@.service is an error. Instances come back via the bootstrap.
        [[ "$unit" == *"@.service" ]] && continue
        if [[ "$enabled" == enabled ]]; then
            run systemctl enable "$unit" || true
        fi
        if [[ "$active" == active ]]; then
            run systemctl start "$unit" || true
        fi
    done < "$BACKUP_DIR/manifest"

    say "Rollback done. Check: systemctl status shelly-web shelly-thinkers@audel"
    exit 0
fi

########################################################################
# Preflight
########################################################################
say "Preflight"

for pair in "${UNIT_PAIRS[@]}"; do
    new="${pair#*:}"
    [[ -f "$APP_DIR/deploy/$new" ]] \
        || { echo "error: missing $APP_DIR/deploy/$new — is the repo on the rename commit?" >&2; exit 1; }
done
[[ -f "$APP_DIR/deploy/headlong-thinkersctl" ]] \
    || { echo "error: missing $APP_DIR/deploy/headlong-thinkersctl" >&2; exit 1; }

# No compat aliases this time: the headlong-* console scripts must already
# be in the venvs (deploy update.sh ran on the rename commit) or the new
# units will have nothing to exec.
for proj_bin in web/.venv/bin/headlong-web slack/.venv/bin/headlong-slack-bridge \
                telegram/.venv/bin/headlong-telegram-bridge; do
    proj="${proj_bin%%/*}"
    # Optional components: only require the binary if the component's legacy
    # unit is actually installed.
    case "$proj" in
        slack)    [[ -f "$SYSD/shelly-slack-bridge.service" ]] || continue ;;
        telegram) [[ -f "$SYSD/shelly-telegram-bridge.service" ]] || continue ;;
    esac
    [[ -x "$APP_DIR/$proj_bin" ]] \
        || { echo "error: missing $APP_DIR/$proj_bin — run deploy/update.sh (uv sync) on the rename commit first" >&2; exit 1; }
done

installed_legacy=0
for pair in "${UNIT_PAIRS[@]}"; do
    [[ -f "$SYSD/${pair%%:*}" ]] && installed_legacy=1
done
if [[ $installed_legacy -eq 0 ]]; then
    say "No shelly-* units installed — already migrated. Nothing to do."
    exit 0
fi

mapfile -t INSTANCES < <(thinker_instances shelly-thinkers)
say "Thinkers instances to bring back: ${INSTANCES[*]:-(none)}"

########################################################################
# Backup
########################################################################
say "Backing up current units and helpers to $BACKUP_DIR"
run mkdir -p "$BACKUP_DIR/units"

# Record enabled/active BEFORE anything stops, so the new units land in the
# same state (and rollback can restore it).
manifest=""
for pair in "${UNIT_PAIRS[@]}"; do
    legacy="${pair%%:*}"
    [[ -f "$SYSD/$legacy" ]] || continue
    run cp -a "$SYSD/$legacy" "$BACKUP_DIR/units/$legacy"
    # `systemctl is-enabled` prints "disabled" AND exits 1, so a naive
    # `|| echo unknown` appends a second line and splits the manifest
    # record in two — which would leave rollback unable to see the
    # `active` field and silently not restart the unit. Take the status
    # separately, and keep only the first line.
    en=$(systemctl is-enabled "$legacy" 2>/dev/null) || true
    ac=$(systemctl is-active "$legacy" 2>/dev/null) || true
    en=${en%%$'\n'*}; [[ -n "$en" ]] || en=unknown
    ac=${ac%%$'\n'*}; [[ -n "$ac" ]] || ac=unknown
    manifest+="$legacy"$'\t'"$en"$'\t'"$ac"$'\n'
    printf '    %-36s enabled=%-10s active=%s\n' "$legacy" "$en" "$ac"
done
if [[ -d "$SYSD/shelly-web.service.d" ]]; then
    run cp -a "$SYSD/shelly-web.service.d" "$BACKUP_DIR/units/"
fi
if [[ -f $LOCAL_BIN/shelly-thinkersctl ]]; then
    run cp -a $LOCAL_BIN/shelly-thinkersctl "$BACKUP_DIR/"
fi
if [[ -f $SUDOERS_D/shelly-thinkers ]]; then
    run cp -a $SUDOERS_D/shelly-thinkers "$BACKUP_DIR/sudoers-shelly-thinkers"
fi
if [[ -f $AUDIT_D/shelly-signals.rules ]]; then
    run cp -a $AUDIT_D/shelly-signals.rules "$BACKUP_DIR/"
fi

if [[ $DRY_RUN -eq 1 ]]; then
    printf '    [dry-run] write manifest (%d units)\n' "$(printf '%s' "$manifest" | grep -c . || true)"
else
    printf '%s' "$manifest" > "$BACKUP_DIR/manifest"
fi

########################################################################
# Stop
########################################################################
say "Stopping legacy units (the dispatchers drain — this can take ~3 min)"
for unit in "${STOP_ORDER[@]}"; do
    [[ -f "$SYSD/$unit" ]] || continue
    run systemctl stop "$unit" || true
done
for ident in "${INSTANCES[@]:-}"; do
    [[ -n "$ident" ]] || continue
    say "Stopping shelly-thinkers@$ident"
    run systemctl stop "shelly-thinkers@$ident.service" || true
done

########################################################################
# Swap the files
########################################################################
say "Removing legacy units and installing headlong-* units"
for pair in "${UNIT_PAIRS[@]}"; do
    legacy="${pair%%:*}"
    [[ -f "$SYSD/$legacy" ]] || continue
    # disable before removal so the symlinks in */.wants are cleaned up;
    # a leftover dangling .wants symlink fails the next daemon-reload.
    run systemctl disable "$legacy" || true
    run rm -f "$SYSD/$legacy"
done

# Deleting a unit file leaves systemd holding a stale not-found/failed
# entry for the old name, which then shows up in `systemctl --failed` —
# the first thing incident triage reads. Clear them so the box does not
# advertise phantom failures forever.
for pair in "${UNIT_PAIRS[@]}"; do
    run systemctl reset-failed "${pair%%:*}" || true
done
for ident in "${INSTANCES[@]:-}"; do
    [[ -n "$ident" ]] || continue
    run systemctl reset-failed "shelly-thinkers@$ident.service" || true
done

# The box-local drop-in (CORS origin, etc.) has to follow the unit name or
# it stops applying — silently, since systemd just ignores an orphan dir.
# SHELLY_* var names inside it are rewritten to HEADLONG_* (there is no
# SHELLY_ fallback in headlong_web/env.py anymore); operator-set SHELLM_*
# names keep working through env.py's SHELLM_ fallback, which stays until
# the parked /opt/shellm world is renamed.
if [[ -d "$SYSD/shelly-web.service.d" ]]; then
    say "Moving drop-in shelly-web.service.d -> headlong-web.service.d"
    run mv "$SYSD/shelly-web.service.d" "$SYSD/headlong-web.service.d"
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    [dry-run] rewrite SHELLY_ -> HEADLONG_ in headlong-web.service.d/*.conf\n'
    else
        for conf in "$SYSD/headlong-web.service.d"/*.conf; do
            [[ -f "$conf" ]] || continue
            sed -i -e 's/\bSHELLY_/HEADLONG_/g' \
                -e 's|/usr/local/bin/shelly-thinkersctl|/usr/local/bin/headlong-thinkersctl|g' "$conf"
        done
    fi
fi

for pair in "${UNIT_PAIRS[@]}"; do
    new="${pair#*:}"
    if [[ $DRY_RUN -eq 1 ]]; then
        printf '    [dry-run] render+install %s\n' "$new"
    else
        sed "s|@SHELLM_HOME@|$SHELLM_HOME|g" "$APP_DIR/deploy/$new" \
            > "$SYSD/$new"
        chown root:root "$SYSD/$new"
        chmod 0644 "$SYSD/$new"
    fi
done

say "Installing headlong-thinkersctl, sudoers, audit rules (single names — no compat)"
run install -o root -g root -m 0755 "$APP_DIR/deploy/headlong-thinkersctl" "$LOCAL_BIN/headlong-thinkersctl"
# Sweep BOTH prior generations of the wrapper.
run rm -f "$LOCAL_BIN/shelly-thinkersctl" "$LOCAL_BIN/shellm-thinkersctl"
if [[ -f "$APP_DIR/deploy/sudoers-headlong-thinkers" ]]; then
    if visudo -cf "$APP_DIR/deploy/sudoers-headlong-thinkers" >/dev/null; then
        run install -o root -g root -m 0440 "$APP_DIR/deploy/sudoers-headlong-thinkers" $SUDOERS_D/headlong-thinkers
        run rm -f $SUDOERS_D/shelly-thinkers $SUDOERS_D/shellm-thinkers
    else
        echo "==> ERROR: sudoers-headlong-thinkers failed visudo — keeping the old rule" >&2
    fi
fi
if [[ -f "$APP_DIR/deploy/audit-headlong-signals.rules" ]]; then
    run install -o root -g root -m 0640 "$APP_DIR/deploy/audit-headlong-signals.rules" $AUDIT_D/headlong-signals.rules
    run rm -f $AUDIT_D/shelly-signals.rules $AUDIT_D/shellm-signals.rules
    run augenrules --load || echo "==> WARN: augenrules --load failed — rules apply after next reboot" >&2
fi

run systemctl daemon-reload

########################################################################
# Start
########################################################################
say "Starting headlong-* units"
# Enable whatever was enabled before. Templates are never enabled; their
# instances come up through the slack persona bootstrap, same as on boot.
while IFS=$'\t' read -r unit enabled _active; do
    [[ "$enabled" == enabled ]] || continue
    new=""
    for pair in "${UNIT_PAIRS[@]}"; do
        [[ "${pair%%:*}" == "$unit" ]] && new="${pair#*:}"
    done
    # Templates are never enabled; their instances come up via the
    # bootstrap. `systemctl enable foo@.service` with no instance errors.
    if [[ -n "$new" && "$new" != *"@.service" ]]; then
        run systemctl enable "$new" || true
    fi
done < <(if [[ $DRY_RUN -eq 1 ]]; then printf '%s' "$manifest"; else cat "$BACKUP_DIR/manifest"; fi)

# Web first so the dash is up to watch the rest. Then the persona bootstrap,
# whose ExecStart calls `headlong-thinkersctl restart <identity>` and brings
# the mind back — the same path every reboot takes. Then the bridges.
for unit in headlong-web.service headlong-slack-agent.service \
            headlong-slack-bridge.service headlong-telegram-bridge.service; do
    # In a dry run nothing was installed, so test the repo source instead —
    # otherwise the rehearsal skips the entire start phase and shows
    # nothing about the step most worth rehearsing.
    if [[ $DRY_RUN -eq 1 ]]; then
        [[ -f "$APP_DIR/deploy/$unit" ]] || continue
    else
        [[ -f "$SYSD/$unit" ]] || continue
    fi
    say "Starting $unit"
    run systemctl start "$unit" || echo "==> WARN: $unit failed to start" >&2
done

# The bootstrap should have restarted every mind that was running. Anything
# it does not manage (a non-persona identity) gets started explicitly.
for ident in "${INSTANCES[@]:-}"; do
    [[ -n "$ident" ]] || continue
    if [[ $DRY_RUN -eq 0 ]] && systemctl is-active --quiet "headlong-thinkers@$ident.service"; then
        continue
    fi
    say "Starting headlong-thinkers@$ident (not brought up by the bootstrap)"
    run systemctl start "headlong-thinkers@$ident.service" || true
done

########################################################################
# Verify
########################################################################
if [[ $DRY_RUN -eq 1 ]]; then
    say "Dry run complete — nothing changed."
    exit 0
fi

say "Verifying"
fail=0
for pair in "${UNIT_PAIRS[@]}"; do
    new="${pair#*:}"
    [[ -f "$SYSD/$new" ]] || continue
    [[ "$new" == *"@.service" ]] && continue   # templates have no state
    st=$(systemctl is-active "$new" 2>/dev/null || true)
    printf '    %-36s %s\n' "$new" "$st"
    # slack-agent is a oneshot: "active (exited)" is success.
    [[ "$st" == active ]] || fail=1
done
for ident in "${INSTANCES[@]:-}"; do
    [[ -n "$ident" ]] || continue
    st=$(systemctl is-active "headlong-thinkers@$ident.service" 2>/dev/null || true)
    printf '    %-36s %s\n' "headlong-thinkers@$ident.service" "$st"
    [[ "$st" == active ]] || fail=1
    # The self-stop guard matches the dispatcher's cgroup by unit name. If
    # the cgroup does not carry the new name the guard is not protecting
    # this mind, which is the exact failure the rename could introduce.
    dpid=$(cat "$APP_DIR/.identities/$ident/run/dispatcher.pid" 2>/dev/null || true)
    if [[ -n "$dpid" ]] && grep -q "headlong-thinkers@$ident.service" "/proc/$dpid/cgroup" 2>/dev/null; then
        printf '    %-36s guard cgroup OK (pid %s)\n' "" "$dpid"
    else
        printf '    %-36s GUARD CGROUP NOT CONFIRMED (pid %s)\n' "" "${dpid:-none}"
        fail=1
    fi
done

for _ in $(seq 1 36); do
    if curl -fsS localhost:8080/api/health >/dev/null 2>&1; then
        say "Healthy: $(curl -fsS localhost:8080/api/health)"
        break
    fi
    sleep 5
done

if [[ $fail -ne 0 ]]; then
    echo "==> ERROR: migration finished with problems. Roll back with:" >&2
    echo "      sudo bash $0 --rollback" >&2
    echo "    (after reverting the checkout — see the header notes)" >&2
    exit 1
fi

say "Migration complete. Backup kept at $BACKUP_DIR (rollback: $0 --rollback)"
