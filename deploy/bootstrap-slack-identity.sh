#!/usr/bin/env bash
set -euo pipefail

# deploy/bootstrap-slack-identity.sh — idempotent bootstrap for the Slack
# persona: create the identity if missing, install its persona prompt, and
# make sure the monolith thinker dispatcher is running.
#
# Runs as the shellm user via shellm-slack-agent.service (oneshot); safe to
# re-run any time. Usage: bootstrap-slack-identity.sh [APP_DIR]

APP_DIR="${1:-/opt/shellm/app}"
cd "$APP_DIR"
export PATH="$APP_DIR/bin:$PATH"

# Root .env carries SHELLM_SLACK_IDENTITY (and the API keys thinkers need)
if [[ -f "$APP_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$APP_DIR/.env"
    set +a
fi
name="${SHELLM_SLACK_IDENTITY:-audel}"

# The identity CLI treats IDENTITY_DIR as the identities ROOT when no
# identity is active (same convention as the web server's control plane).
unset IDENTITY_NAME
export IDENTITY_DIR="$APP_DIR/.identities"
mkdir -p "$IDENTITY_DIR"

if [[ ! -d "$IDENTITY_DIR/$name" ]]; then
    echo "==> Creating identity '$name'"
    identity new "$name"
fi

if [[ ! -f "$IDENTITY_DIR/$name/core_identity_prompt.md" && -f "$APP_DIR/deploy/slack-persona.md" ]]; then
    echo "==> Installing persona prompt"
    cp "$APP_DIR/deploy/slack-persona.md" "$IDENTITY_DIR/$name/core_identity_prompt.md"
fi

# Activate the identity (exports IDENTITY_NAME, TRAJ_DIR, THINKERS_DIR, ...)
# shellcheck disable=SC1091
source "$IDENTITY_DIR/$name/activate"

if thinkers status 2>/dev/null | grep -q 'Dispatcher: running'; then
    echo "==> Dispatcher already running"
else
    echo "==> Starting monolith thinker"
    thinkers start monolith
fi

echo "==> Persona '$name' ready"
