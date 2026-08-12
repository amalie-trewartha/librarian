# Insertion point: within-response repetition detector

## Problem
g001r4: z-ai/glm-5.2 emitted ~100 identical bash blocks in a SINGLE
iteration response, burning the 60s timeout. g001r1 (same model)
succeeded. So this is a context-dependent model generation issue,
not a shellm bug — but shellm can defend against it.

## Actor loop location
File: /opt/shellm/app/bin/shellm

- Line ~2036-2038: `progress "Iteration $iter_label — calling $SHELLM_MODEL..."`
- Line ~2109: `code=$(extract_code "$response")`  ← model response parsed here
- Lines ~1330-1360: `extract_code` awk function — parses ```bash fences

## Insertion point (recommended)
Right AFTER `extract_code` returns (line ~2109) and BEFORE the code
is executed. Add a repetition check on `$response`:

```bash
code=$(extract_code "$response")

# --- within-response repetition detector ---
n_blocks=$(printf '%s\n' "$response" | grep -cE '^```(bash|sh)?[[:space:]]*$')
if (( n_blocks > 5 )); then
    # dedupe identical blocks by their first content line
    dup_ratio=$(printf '%s\n' "$response" \
        | awk '/^```(bash|sh)?[[:space:]]*$/{in=1;next} /^```[[:space:]]*$/{in=0;next} in{print}' \
        | sort | uniq -c | sort -rn | head -1 | awk '{print $1}')
    if (( dup_ratio > 5 )); then
        progress "Repetition detected ($n_blocks blocks, top dup $dup_ratio) — aborting iteration"
        # append a traj step + break, or inject a corrective system note
    fi
fi
```

## 4 candidate fixes (from findings note)
1. Within-response repetition detector (above) — cheapest, recommended.
2. Per-iteration token/time budget with early stop on diminishing novelty.
3. Strip/normalize repeated blocks before execution.
4. Inject a "you are repeating" corrective message on detection.

## Status
Diagnosis complete. Patch drafted. Next: apply + test on g001r4 scenario.
