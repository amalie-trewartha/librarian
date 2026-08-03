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
  (see `terraform.tfvars.example` and `../slack-manifest.yaml` for creating
  the Slack app).
- `user_data.sh.tpl` runs setup with `SHELLM_INSTALL_SLACK_BRIDGE=1`, which
  installs the `shellm-slack-agent` (persona bootstrap) and
  `shellm-slack-bridge` (Socket Mode client) units alongside `shellm-web`.

Day-2 via the shared scripts: `SHELLM_TF_STACK=terraform-slack
deploy/scripts/update` (likewise `status` / `shell` / `stop` / `start`).
