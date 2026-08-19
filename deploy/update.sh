#!/usr/bin/env bash
set -euo pipefail

# deploy/update.sh — pull the deploy branch, force a frontend rebuild,
# restart the web service. Running agents are untouched (dispatchers live
# in their own sessions).
#
# From your laptop:  eval "$(terraform output -raw update_command)"
# From an SSM session:  sudo bash /opt/shellm/app/deploy/update.sh

APP_DIR="${APP_DIR:-/opt/shellm/app}"
UNIT_DST="${UNIT_DST:-/etc/systemd/system/shellm-web.service}"

echo "==> Pulling latest"
sudo -u shellm git -C "$APP_DIR" pull --ff-only

# Re-sync the systemd unit from the repo so unit changes deploy like code.
# Box-local customization belongs in shellm-web.service.d/override.conf
# (drop-ins survive this); hand-edits to the main unit will be overwritten.
UNIT_SRC="$APP_DIR/deploy/shellm-web.service"
SHELLM_HOME="${SHELLM_HOME:-$(dirname "$APP_DIR")}"
if [[ -f "$UNIT_SRC" ]]; then
    rendered=$(sed "s|@SHELLM_HOME@|$SHELLM_HOME|g" "$UNIT_SRC")
    if ! printf '%s\n' "$rendered" | cmp -s - "$UNIT_DST" 2>/dev/null; then
        echo "==> Unit file changed — re-installing $UNIT_DST"
        printf '%s\n' "$rendered" | sudo tee "$UNIT_DST" >/dev/null
        sudo systemctl daemon-reload
    fi
fi

# Per-identity thinkers: template unit + root wrapper + sudo rule. Synced
# like the web unit so changes deploy as code. The wrapper and sudo rule
# are what let the dash (user shellm) start dispatchers in their own
# cgroup; the sudoers file is only installed if it passes visudo's check,
# because a malformed sudoers file breaks sudo box-wide.
for unit_tpl in shellm-thinkers@ shellm-thinkers-alert@; do
    unit_src="$APP_DIR/deploy/${unit_tpl}.service"
    [[ -f "$unit_src" ]] || continue
    rendered=$(sed "s|@SHELLM_HOME@|$SHELLM_HOME|g" "$unit_src")
    if ! printf '%s\n' "$rendered" | cmp -s - "/etc/systemd/system/${unit_tpl}.service" 2>/dev/null; then
        echo "==> Unit file changed — re-installing ${unit_tpl}"
        printf '%s\n' "$rendered" | sudo tee "/etc/systemd/system/${unit_tpl}.service" >/dev/null
        sudo systemctl daemon-reload
    fi
done
if [[ -f "$APP_DIR/deploy/shellm-thinkersctl" ]] \
    && ! cmp -s "$APP_DIR/deploy/shellm-thinkersctl" /usr/local/bin/shellm-thinkersctl 2>/dev/null; then
    echo "==> Installing shellm-thinkersctl wrapper"
    sudo install -o root -g root -m 0755 "$APP_DIR/deploy/shellm-thinkersctl" /usr/local/bin/shellm-thinkersctl
fi
if [[ -f "$APP_DIR/deploy/sudoers-shellm-thinkers" ]] \
    && ! sudo cmp -s "$APP_DIR/deploy/sudoers-shellm-thinkers" /etc/sudoers.d/shellm-thinkers 2>/dev/null; then
    if sudo visudo -cf "$APP_DIR/deploy/sudoers-shellm-thinkers"; then
        echo "==> Installing sudoers rule for shellm-thinkersctl"
        sudo install -o root -g root -m 0440 "$APP_DIR/deploy/sudoers-shellm-thinkers" /etc/sudoers.d/shellm-thinkers
    else
        echo "==> ERROR: deploy/sudoers-shellm-thinkers failed the visudo check — skipped" >&2
    fi
fi

# Signal-audit rules (kernel-level kill attribution, see
# deploy/audit-shellm-signals.rules). Existing boxes get auditd via this
# path — setup.sh only runs on fresh provisions.
if [[ -f "$APP_DIR/deploy/audit-shellm-signals.rules" ]] \
    && ! sudo cmp -s "$APP_DIR/deploy/audit-shellm-signals.rules" /etc/audit/rules.d/shellm-signals.rules 2>/dev/null; then
    if ! command -v augenrules >/dev/null 2>&1; then
        echo "==> Installing auditd"
        sudo DEBIAN_FRONTEND=noninteractive apt-get install -y auditd >/dev/null
    fi
    echo "==> Audit rules changed — re-installing shellm-signals.rules"
    sudo install -o root -g root -m 0640 "$APP_DIR/deploy/audit-shellm-signals.rules" /etc/audit/rules.d/shellm-signals.rules
    sudo augenrules --load || echo "==> WARN: augenrules --load failed — rules apply after next reboot" >&2
fi

# Optional component: Slack bridge (installed on boxes provisioned with
# SHELLM_INSTALL_SLACK_BRIDGE=1). Re-sync its units + deps and restart the
# bridge; the persona bootstrap (oneshot) is left alone so the running
# dispatcher is untouched.
if [[ -f /etc/systemd/system/shellm-slack-bridge.service ]]; then
    echo "==> Updating Slack bridge"
    for unit in shellm-slack-agent shellm-slack-bridge; do
        unit_src="$APP_DIR/deploy/$unit.service"
        if [[ -f "$unit_src" ]]; then
            rendered=$(sed "s|@SHELLM_HOME@|$SHELLM_HOME|g" "$unit_src")
            if ! printf '%s\n' "$rendered" | cmp -s - "/etc/systemd/system/$unit.service" 2>/dev/null; then
                echo "==> Unit file changed — re-installing $unit"
                printf '%s\n' "$rendered" | sudo tee "/etc/systemd/system/$unit.service" >/dev/null
                sudo systemctl daemon-reload
            fi
        fi
    done
    sudo -u shellm bash -c "export PATH=\"\$HOME/.local/bin:\$PATH\"; cd '$APP_DIR/slack' && uv sync"
    sudo systemctl restart shellm-slack-bridge
fi

# Optional component: Telegram bridge. Enabled post-hoc on a live box by
# writing /etc/shellm/telegram.env (root:root 600 with TELEGRAM_BOT_TOKEN +
# TELEGRAM_ADMIN_ID) — there is no bootstrap flag because user_data must
# never change (instance replacement). See telegram/README.md.
if [[ -f /etc/shellm/telegram.env ]]; then
    echo "==> Updating Telegram bridge"
    sudo chown root:root /etc/shellm/telegram.env
    sudo chmod 600 /etc/shellm/telegram.env
    # Dedicated user: keeps the bot token and the allowlist out of the
    # agent's reach (the agent runs as shellm). Group shellm grants
    # read-only access to the identity's trajectory.
    if ! id -u shellm-telegram >/dev/null 2>&1; then
        sudo useradd --system --no-create-home --shell /usr/sbin/nologin shellm-telegram
    fi
    sudo usermod -aG shellm shellm-telegram
    sudo chmod g+rx "$SHELLM_HOME"
    sudo -u shellm bash -c "export PATH=\"\$HOME/.local/bin:\$PATH\"; cd '$APP_DIR/telegram' && uv sync"
    unit_src="$APP_DIR/deploy/shellm-telegram-bridge.service"
    rendered=$(sed "s|@SHELLM_HOME@|$SHELLM_HOME|g" "$unit_src")
    if ! printf '%s\n' "$rendered" | cmp -s - /etc/systemd/system/shellm-telegram-bridge.service 2>/dev/null; then
        echo "==> Unit file changed — re-installing shellm-telegram-bridge"
        printf '%s\n' "$rendered" | sudo tee /etc/systemd/system/shellm-telegram-bridge.service >/dev/null
        sudo systemctl daemon-reload
    fi
    sudo systemctl enable --now shellm-telegram-bridge >/dev/null 2>&1 || true
    sudo systemctl restart shellm-telegram-bridge
fi

echo "==> Forcing frontend rebuild on restart"
sudo -u shellm rm -rf "$APP_DIR/web/src/shelly_web/static"

echo "==> Restarting shellm-web (rebuild takes ~1-2 min)"
sudo systemctl restart shellm-web

for _ in $(seq 1 36); do
    if curl -fsS localhost:8080/api/health >/dev/null 2>&1; then
        echo "==> Healthy: $(curl -fsS localhost:8080/api/health)"
        echo "==> Now running: $(sudo -u shellm git -C "$APP_DIR" log -1 --oneline)"
        exit 0
    fi
    sleep 5
done

echo "==> ERROR: service not healthy after 3 minutes; check: journalctl -u shellm-web -n 50" >&2
exit 1
