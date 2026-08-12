#!/usr/bin/env bash
# Within-response repetition detector — counts identical bash code blocks
# in a single model response. If the same block (normalized) repeats more
# than THRESHOLD times, flag it so the actor can abort early instead of
# burning the iteration timeout.
set -euo pipefail

THRESHOLD="${REP_THRESHOLD:-3}"

count_bash_blocks() {
    local response="$1"
    # Extract first bash block only (matches extract_code's first-block logic).
    # For detection we want ALL blocks — parse every fenced block.
    printf '%s\n' "$response" | awk -v thr="$THRESHOLD" '
        BEGIN { in_block=0; count=0; idx=0 }
        /^```bash/ || /^```sh/ || /^```/ {
            if (in_block) { in_block=0; idx++; blocks[idx]=buf; buf="" }
            else { in_block=1; buf="" }
            next
        }
        in_block { buf = buf $0 "\n" }
        END {
            if (in_block && buf!="") { idx++; blocks[idx]=buf }
            # count duplicates
            for (i=1;i<=idx;i++) {
                for (j=i+1;j<=idx;j++) {
                    if (blocks[i]==blocks[j] && blocks[i]!="") { dup++ }
                }
            }
            print idx, dup+0
        }
    '
}

detect_repetition() {
    local response="$1"
    read -r total dup <<<"$(count_bash_blocks "$response")"
    if (( dup >= THRESHOLD )); then
        echo "REPETITIVE: $total blocks, $dup duplicate pairs (threshold=$THRESHOLD)"
        return 1
    fi
    echo "OK: $total blocks, $dup duplicate pairs (threshold=$THRESHOLD)"
    return 0
}

# --- tests ---
mkblock() { printf '```bash\n%s\n```\n' "$1"; }

# Case 1: normal single-block response
NORMAL=$(mkblock 'cd /tmp; ls -la')
echo "[case1 normal] $(detect_repetition "$NORMAL")"

# Case 2: two distinct blocks (still OK)
TWO=$(mkblock 'cd /tmp' ; mkblock 'ls -la')
echo "[case2 two-distinct] $(detect_repetition "$TWO")"

# Case 3: repetitive response — same block 10x (mimics g001r4)
REP=$(for i in $(seq 1 10); do mkblock 'cd "${SHELLM_WORKDIR:-/tmp}" 2>/dev/null || cd /tmp'; done)
echo "[case3 repetitive 10x] $(detect_repetition "$REP")"


# --- block-count threshold (catches near-duplicate repetition) ---
# Counts total bash code blocks in the input file. If the count exceeds
# BLOCK_THRESHOLD (default 15), flags as REPETITIVE. This catches the
# real g001r4 failure mode: many near-duplicate blocks (not exact dup pairs).
block_count_threshold() {
  local file="${1:-/dev/stdin}"
  local threshold="${BLOCK_THRESHOLD:-15}"
  [ -f "$file" ] || file=/dev/stdin
  awk '
    /^```bash/ || /^```sh/ || /^```[[:space:]]*$/ { in_block = !in_block; if (in_block) n++ }
    END { print n+0 }
  ' "$file"
}

# If invoked with a file arg (or stdin), run the block-count + dup-pair checks
# on that input in addition to (or instead of) the synthetic cases.
if [ -n "${1:-}" ] || [ ! -t 0 ]; then
  INPUT="${1:-/dev/stdin}"
  TOTAL=$(block_count_threshold "$INPUT")
  DUP_PAIRS=$(awk '
    BEGIN { in_block=0; idx=0 }
    /^```bash/ || /^```sh/ || /^```[[:space:]]*$/ {
      if (in_block) { blocks[idx]=buf; buf=""; in_block=0 }
      else { idx++; $0=""; in_block=1; buf="" }
      next
    }
    in_block { buf = buf "\n" $0 }
    END {
      if (in_block && buf!="") { idx++; blocks[idx]=buf }
      # count exact duplicate pairs
      for (i=1;i<=idx;i++) for (j=i+1;j<=idx;j++) if (blocks[i]==blocks[j]) d++
      print d+0
    }
  ' "$INPUT" 2>/dev/null || echo 0)
  THRESH="${DUP_THRESHOLD:-3}"
  BT="${BLOCK_THRESHOLD:-15}"
  echo "[real-input] total_blocks=$TOTAL dup_pairs=$DUP_PAIRS (dup_threshold=$THRESH block_threshold=$BT)"
  if [ "$DUP_PAIRS" -ge "$THRESH" ] || [ "$TOTAL" -ge "$BT" ]; then
    echo "[real-input] REPETITIVE"
  else
    echo "[real-input] OK"
  fi
fi
