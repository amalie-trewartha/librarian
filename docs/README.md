# docs/

Reference documentation.

- [install.md](install.md) covers every install variant, including
  non-interactive/CI installs and the long-lived Docker container.
- [project-mode-setup.md](project-mode-setup.md) takes a fresh machine to a
  running project-mode agent (long unattended research runs), Bedrock
  credentials and budgets included.
- [headlong-bedrock-env](headlong-bedrock-env) writes a new install's
  `~/.headlong/.env` (and its rotatable key file) from an `aws.env`. Run
  `docs/headlong-bedrock-env ~/aws.env --check`; it is the same tool that
  `install.sh` puts on your PATH (a link to `tools/headlong-bedrock-env`).
- [shellm.md](shellm.md) is the shellm engine reference: the loop,
  context passing, Docker sandboxing, envs, the `llm` tool, and options.
- [RELEASING.md](RELEASING.md) is the playbook for tagging a release on
  GitHub before an announcement: checklist, commands, pinned install line.

The design story and the case for the microharness are in
[philosophy.md](../philosophy.md), and design documents live in
[design/](../design/).
