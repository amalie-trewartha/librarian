# tests/

Test scripts for the harness. Each `test_*.sh` is a self-contained
executable, so run one directly, e.g. `tests/test_context.sh`.

`fixtures/` holds small trajectories the tests render, and `golden/`
holds the expected outputs. `tests/test_context.sh --regen` regenerates
the golden files from the current `bin/context` after an intentional
output change.
