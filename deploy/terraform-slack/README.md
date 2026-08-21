# terraform-slack

Dedicated instance for the Slack persona (`audel`), an intentional sibling
copy of [`../terraform`](../terraform/README.md) — that README's tooling,
provisioning, and day-2 instructions all apply here, with these deltas:

- `subdomain = "slack"` → dash at `https://slack.shellm.net` (Cloudflare
  Access OTP, observability only; Slack traffic uses Socket Mode and never
  enters through the tunnel).
- `env_parameter = "/shellm-slack/env"` — this box's own SSM SecureString.
  Seed it **before** `terraform apply` with the LLM key(s) plus
  `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, and `SHELLM_SLACK_IDENTITY=audel`
  (see `terraform.tfvars.example`; the Slack app itself is created and
  managed from `slack/manifest.json` via the Slack CLI — see `slack/README.md`).
- `user_data.sh.tpl` runs setup with `SHELLM_INSTALL_SLACK_BRIDGE=1`, which
  installs the `headlong-slack-agent` (persona bootstrap) and
  `headlong-slack-bridge` (Socket Mode client) units alongside `headlong-web`.
- Optional Google SSO for the dash: set `allowed_email_domains` +
  `google_oauth_client_id` in tfvars (see `terraform.tfvars.example`) and
  the client secret via `TF_VAR_google_oauth_client_secret` in `.envrc`
  (see `envrc.example`). Manual prerequisite in Google Cloud console: an
  OAuth client (type Web application, no JavaScript origins) whose redirect
  URI is `https://<team>.cloudflareaccess.com/cdn-cgi/access/callback` —
  the team name is under Zero Trust → Settings → Custom Pages. The client
  can live in any GCP project: with a consent screen inside the Workspace
  org, pick "Internal" (only org accounts can authenticate); in a personal
  project, "External" + published works fine — anyone can authenticate, but
  the Access policy's email/domain check is the gate that matters either
  way. OTP stays enabled regardless (the login picker appears once both
  IdPs exist).

Day-2 via the shared scripts: `SHELLM_TF_STACK=terraform-slack
deploy/scripts/update` (likewise `status` / `shell` / `stop` / `start`).
