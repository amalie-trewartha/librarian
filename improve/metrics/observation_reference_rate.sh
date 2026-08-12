#!/usr/bin/env bash
# Metric: observation-referencing rate.
#
# Fraction of post-observation thoughts that mention content from the
# preceding observation. Crude keyword overlap per next-steps.md line 12.
#
# Usage: observation_reference_rate.sh <trajectory.jsonl>
#   Prints: observations=N thoughts_referencing=M rate=0.XX
set -euo pipefail

TRAJ_FILE="${1:-}"
if [[ -z "$TRAJ_FILE" || ! -f "$TRAJ_FILE" ]]; then
    echo "Usage: $0 <trajectory.jsonl>" >&2
    exit 1
fi

# Step 1: Extract ordered pairs of (type, content) using jq.
# We emit TSV lines: type<TAB>content for every step that has a type field.
mapfile -t STEPS < <(jq -r 'select(.type != null) | [.type, (.content // "")] | @tsv' "$TRAJ_FILE" 2>/dev/null)

# Stopwords (common words to ignore when extracting keywords).
STOPWORDS=$(cat <<'EOF'
the a an and or but in on at to for of is it this that from with as be was were are by not no do did has had have will would can could should if then than so too very just also only about into over under more most some any all each other such own same
EOF
)

# Function: extract significant keywords from text (lowercase, alphanumeric, >=4 chars, no stopwords).
extract_keywords() {
    local text="$1"
    echo "$text" | tr '[:upper:]' '[:lower:]' | grep -oP '[a-z0-9]{4,}' | while read -r w; do
        if ! echo "$STOPWORDS" | tr ' ' '\n' | grep -qx "$w"; then
            echo "$w"
        fi
    done
}

OBS_COUNT=0
REF_COUNT=0

# Step 2: Walk steps in order. When we see an observation, find the next thought
# and check keyword overlap.
for ((i=0; i<${#STEPS[@]}; i++)); do
    line="${STEPS[$i]}"
    type="${line%%$'\t'*}"
    content="${line#*$'\t'}"

    if [[ "$type" == "observation" ]]; then
        ((OBS_COUNT++)) || true
        # Extract keywords from this observation.
        mapfile -t KEYWORDS < <(extract_keywords "$content")

        # Find the next thought step after this observation.
        for ((j=i+1; j<${#STEPS[@]}; j++)); do
            line2="${STEPS[$j]}"
            type2="${line2%%$'\t'*}"
            content2="${line2#*$'\t'}"

            if [[ "$type2" == "thought" ]]; then
                # Check if any keyword appears in the thought.
                thought_lower=$(echo "$content2" | tr '[:upper:]' '[:lower:]')
                for kw in "${KEYWORDS[@]}"; do
                    if [[ -n "$kw" && "$thought_lower" == *"$kw"* ]]; then
                        ((REF_COUNT++)) || true
                        break
                    fi
                done
                break  # Only check the first thought after the observation.
            fi
        done
    fi
done

# Step 3: Compute and print rate.
if [[ "$OBS_COUNT" -eq 0 ]]; then
    echo "observations=0 thoughts_referencing=0 rate=N/A"
else
    rate=$(awk "BEGIN { printf \"%.2f\", $REF_COUNT / $OBS_COUNT }")
    echo "observations=$OBS_COUNT thoughts_referencing=$REF_COUNT rate=$rate"
fi
