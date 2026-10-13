# Rename: Headlong → Librarian (2026-10-13)

Status: done, with back-compat. The repository is now **Librarian**; it was
**Headlong** (a fork of laude-institute/headlong) until this date. The
memory system that gives the project its name is `librarian/`
(design/librarian.md).

## What changed

| Was | Is | Compat |
|---|---|---|
| `headlong-init`, `-web`, `-project`, `-skills`, `-killall`, `-slack-bridge`, `-telegram-bridge` | `librarian-*` in `tools/` | `tools/headlong-*` are symlinks to the new names and install like any tool (`LEGACY_TOOLS` in install.sh) |
| `HEADLONG_*` env vars | `LIBRARIAN_*` | `bin/librarian-env`, sourced by every entry script, exports `LIBRARIAN_X` from `HEADLONG_X` when unset; install.sh and the deploy scripts inline the same mapping |
| `HEADLONG_LIBRARIAN` (memory on/off) | `LIBRARIAN_MEMORY` | mapped |
| `HEADLONG_LIBRARIAN_SRC` | `LIBRARIAN_SRC` | mapped |
| `~/.headlong` | `~/.librarian` | an existing `~/.headlong` is used when `~/.librarian` does not exist; explicit `LIBRARIAN_HOME`/`HEADLONG_HOME` wins |
| `~/.headlong-thinkers` | `~/.librarian-thinkers` | likewise, via `LIBRARIAN_THINKERS_TEMPLATES` |
| Python packages `headlong_web`, `headlong_slack`, `headlong_telegram`, `headlong_librarian` | `librarian_web`, `librarian_slack`, `librarian_telegram`, `librarian` | console scripts `headlong-web`, `headlong-slack-bridge`, `headlong-telegram-bridge` kept as aliases |
| systemd units `headlong-*` | `librarian-*` | `deploy/migrate-units.sh` migrates headlong-* (and shelly-*) units, drop-ins and wrappers; `headlong-thinkersctl` stays as a symlink and the sudoers rule permits both |
| `tui/headlong` crate `headlong-tui` | `tui/librarian`, `librarian-tui` | `bin/chat` and `bin/thinkers` fall back to a `headlong-tui` binary |
| `design/headlong.md` | `design/framework.md` | |
| `https://headlong.ai/install.sh` | `https://raw.githubusercontent.com/amalie-trewartha/Librarian/main/install.sh` | the hosted Headlong installer installs Headlong |

Older `SHELLM_*` framework spellings are honored only where they were
before the rename (`SHELLM_HOME`, the bridge identity/state vars, `env.py`).
`SHELLM_*` is otherwise the shellm tool's own namespace and untouched.

## What deliberately keeps an older name

- `/opt/shellm`, the `shellm` and `shellm-telegram` UNIX users,
  `~shellm/.shellm`, the per-identity `.shellm/` directory, `*.shellm.net`.
- `/var/lib/headlong/identities` on provisioned boxes, the audit key
  `headlong-sig`, `/var/log/headlong-bootstrap.log`.
- The `.pre-headlong-<date>` suffix the installer gives displaced copies.
- The GitHub login `headlong42` in tests and notes, and the upstream
  project `andyk/headlong` that Headlong itself was named after.
- `usb/` (a frozen offline bundle of the Headlong-era tree).

## Why with compat this time

The shelly→headlong rename (99cb54d) dropped compat on purpose and paid
for it with a supervised box migration. This rename lands while a live run
layout (`~/headlong-live`, Bedrock env files, the Vagrant box) still
exports `HEADLONG_*`, and the memory system was built against those
names days earlier. One sourced file is cheaper than a second migration
window. The mapping can be removed once no box exports `HEADLONG_*`
(grep the deploy drop-ins and `~/.librarian/.env` files first).

## Checks

- `tests/test_rename_compat.sh`: a `HEADLONG_*` environment reaches the
  tools as `LIBRARIAN_*`, the old tool names run the new tools, the state
  home falls back, and `LIBRARIAN_MEMORY`/`LIBRARIAN_SRC` map from their
  old names.
- `tests/test_unit_name_couplings.sh` matches `headlong-*` unit names as
  legacy spellings.
- The full bash suite, the four pytest packages and shellcheck pass after
  the rename.
