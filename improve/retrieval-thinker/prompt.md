# retrieval-thinker

Tier-1 keyword retrieval over the memory index. For each incoming thought/
message/observation step, tokenize its content and grep against
mem/index.tsv. If keyword hits surface memory IDs not already in recent
context, escalate via `mem search` and emit an observation step surfacing
the most relevant memory's summary. This is passive memory influence —
memories surface into the stream when the current step resonates with them,
without explicit recall.
