# deploy/

Everything for running an agent on a dedicated box: systemd units for
the thinkers, bridges, and dashboard, the `setup.sh` and `update.sh`
scripts, terraform for the AWS infrastructure, and the operational
scripts in `scripts/` (pulling the box's commits, usage, and metrics).

Start with [DEPLOY.md](DEPLOY.md). [MIGRATIONS.md](MIGRATIONS.md) is the
playbook for structural changes on a box that is running a live mind,
and [SECURITY.md](SECURITY.md) covers the box's security posture.
