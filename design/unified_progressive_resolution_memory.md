Status: NOT YET IMPLEMENTED — design only; no mem children/parent/level fields, no rollup↔mem bridge, no drill-down skill, mem search still O(n).

Related notes:

- [[3. Thinkers Architecture Update - Reconciled Plan]]
- [[1. shellm thinkers design]]
- tiered_memory.md (shellm design/ — the episodic pyramid this generalizes)
- recap.md (shellm design/ — the summarizer this builds on)

## One-sentence plan

Unify all memory types — episodic (trajectory rollups), semantic (goals, beliefs, facts) — into a single progressive-resolution structure where every entry links to both coarser summaries above and finer detail below, and teach the agent a skill for drilling through the levels.

## Diagnosis

Today there are two memory systems that don't know about each other:

1. **`mem`** — semantic, curated. Individual markdown files with frontmatter (id, summary, type, created) and a body. Types include `memory`, `goal`, `belief`, `intention`, `value`. Retrieved by `mem search` (brute-force LLM scan). No internal structure linking entries to each other or to the trajectory.

2. **Tiered rollups** — episodic, automatic. A pyramid of trajectory summaries at geometrically coarsening granularity (tier 1 = 10 steps, tier 2 = 100, tier 3 = 1000). Each rollup carries cited step-ids. Built by `recap`. No connection to semantic memories.

Problems:

- **Semantic memories are flat.** A belief like "meta-yielding thoughts are narration loops" has no link to the episode where it was learned, no finer-grained context, no coarser grouping with related beliefs. It's a leaf with no tree.
- **Episodic rollups are opaque to the mind.** The staircase assembler puts them in context, but the agent can't navigate them — it can't say "zoom into that period" or "what other rollups mention this theme?" There's no skill for it, and the rollup entries don't link to their neighbors or to semantic memories that emerged from them.
- **No cross-references.** A goal formed during episode 47 doesn't point to episode 47. A tier-2 rollup covering a week where a belief was challenged doesn't point to the belief. The two systems are parallel columns with no bridges.
- **`mem search` is O(n) brute force.** Every query concatenates every memory and asks the LLM to find matches. No index, no hierarchy, no way to narrow before reading.

## Insight: progressive resolution is already there, three times

The pattern of "compressed pointer → medium summary → full detail" already appears in three places:

**1. `mem` files themselves:**

```
filename                          → pointer    (1 token)
frontmatter summary               → digest     (~10 tokens)
markdown body                     → full text  (~100 tokens)
```

**2. Tiered rollups:**

```
tier 2 rollup                     → digest of 100 steps  (~50 tokens)
tier 1 rollup                     → digest of 10 steps   (~50 tokens)
raw trajectory steps              → full detail           (~10 tokens each)
```

**3. HNSW / skip lists (the algorithmic analogue):**

```
layer 2 node  → long-range links  (few, coarse)
layer 1 node  → medium-range links
layer 0 node  → all neighbors     (dense, fine)
```

The common shape: each level is a compressed view of the level below, and navigation works by starting coarse and drilling down. The key property HNSW has that we don't: **every node links to nodes at adjacent levels.** Our tiers link down (step-ids) but not up, and our `mem` entries don't link to tiers at all.

## Unified architecture

### The resolution ladder

Every piece of memory — episodic or semantic — lives at a **resolution level** and carries links to both its **children** (finer detail below) and its **parent** (coarser summary above):

```
Level 3:  life arc          "my first week: bootstrapping identity and exploring tools"
            ↕
Level 2:  chapter/theme     "learned to manage narration loops through self-observation"
            ↕
Level 1:  episode/entry     "episode 47: discovered meta-yielding pattern"
            ↕                   ↕
Level 0:  raw steps         traj steps 470-479  |  belief mem file body
```

The `↕` arrows are the new thing. Today we have `↓` (rollups cite step-ids) but not `↑` (a step or mem entry doesn't know which rollup covers it).

### Schema: the universal memory entry

Every entry at every level shares a common envelope:

```yaml
---
id: a1b2c3d4
type: episode | belief | goal | intention | value | fact | theme | arc
level: 1                          # resolution level (0 = raw)
summary: "one-line digest"
created: 2026-08-17 14:30:00

# Progressive resolution links
children:                          # finer detail below
  - {type: step, id: "step-470"}   # raw traj step
  - {type: step, id: "step-471"}
  - {type: mem, id: "f3e2d1c0"}   # another mem entry
parent:                            # coarser summary above
  - {type: mem, id: "b4c5d6e7"}   # the theme/chapter that covers this

# Provenance
source_range: [470, 479]           # traj step range (episodic entries)
source_traj: "c56dcbdb-root"       # which trajectory
model: "claude-opus-4-7"
prompt_version: 1
---

Full body text here. For episodic entries, this is the rollup summary.
For semantic entries (beliefs, goals), this is the curated content.
```

The key additions over today's `mem` format:

- **`level`** — where this entry sits in the resolution hierarchy
- **`children`** — pointers to finer-grained entries or raw steps
- **`parent`** — pointer to the coarser entry that subsumes this one
- **`source_range`** / **`source_traj`** — provenance back to the raw log (even for semantic entries: "this belief was formed during steps 470-479")

### How the three existing patterns map

**`mem` files become level-1 entries** (or level-2 for broad goals/themes). Their filename is still the pointer (level "0.5"), their frontmatter summary is the digest, their body is the full text. The new fields (`children`, `parent`, `level`) are additive — existing mem files without them still work, they're just unlinked leaves.

**Tier-1 rollups become level-1 episodic entries.** Same content, but now each rollup also carries a `parent` link to its tier-2 rollup. Tier-2 rollups are level-2 entries with `parent` links to tier-3, and so on.

**The semantic-episodic bridge:** when `mem add --type belief` is called during episode 47, the new belief entry's `children` includes the step-ids from that episode, and episode 47's entry gains a `children` link to the belief. A goal formed across episodes 40-50 links to all of them; those episodes link back to it.

### Navigation: the drill-down skill

A new skill (`progressive-recall` or extend `recall`) teaches the agent to navigate the hierarchy:

```
Given a query, start at the coarsest level:
1. Scan level-N summaries (few, broad) — find the 1-3 most relevant
2. Follow their `children` links to level N-1 entries
3. Scan those summaries — find the most relevant
4. Repeat until reaching raw steps or mem file bodies
5. Pull the relevant raw content into context
```

This is HNSW's search algorithm adapted to memory: start with long-range coarse pointers, progressively narrow, never scan everything at any level. Cost is O(log N) entries examined, not O(N).

The skill file:

```markdown
# progressive-recall

When you need to recall something from your past or find a relevant memory:

1. Start broad: `mem list --level 3` (or highest available) — scan arc/theme summaries
2. Drill: for the relevant entry, `mem children <id>` — see its finer-grained sub-entries
3. Repeat: `mem children <id>` on the most relevant child until you reach raw steps or full mem bodies
4. Expand: `traj cat <step-range>` to pull raw trajectory steps into context

At each level, you're reading ~10 summaries, not the whole memory.
Never scan all memories at level 0 — always start high and drill down.
```

### Linking mechanics

**Downlinks (children) are created at write time.** When `recap` seals a tier-1 block, it already records the step-ids — these become `children`. When `mem add` is called, the current traj context (last N step-ids) becomes the new entry's `children.source_range`.

**Uplinks (parent) are created when the parent is sealed.** When a tier-2 rollup is created from 10 tier-1 rollups, each tier-1 rollup's entry gains a `parent` link to the new tier-2 entry. Same for semantic entries: when the `learn` route creates a theme mem that groups three beliefs, those beliefs gain `parent` links.

**Cross-links (semantic ↔ episodic) are created by the learning thinker.** When a belief is formed during an episode, the `learn` route:
1. Creates the belief mem with `children` pointing to the source steps
2. Patches the covering episode's entry to add the belief as a child

This is the bridge between the two columns.

### Relationship to HNSW specifically

HNSW has three properties we're borrowing:

1. **Hierarchical layers** — coarse at top, fine at bottom. We have this (tiers).
2. **Navigable links at each layer** — every node links to neighbors at the same level AND to its counterpart one level up and down. We're adding the up/down links; same-level links (related beliefs, adjacent episodes) are a later refinement.
3. **Greedy search from top** — enter at the coarsest layer, follow the best link, descend, repeat. The drill-down skill implements this.

The one HNSW property we don't need: approximate nearest-neighbor guarantees. Our "queries" are natural language interpreted by an LLM at each level, not vector distances. The hierarchy just bounds how many entries the LLM has to scan at each step.

## Relationship to skip lists

Skip lists are the simpler 1D analogue: a sorted linked list with express lanes. Every Nth element appears in the express lane; every N²th in the super-express lane. Search starts at the top lane (few stops, big jumps) and drops down when it overshoots.

Our time-ordered trajectory is exactly a sorted list. The tiered rollups are exactly the express lanes. The addition is making `mem` entries — which aren't time-ordered — also participate in the same hierarchy by linking them to their temporal context (the episode where they were created or are relevant).

## Implementation plan

### Phase 1: Add resolution links to mem

Extend `mem add` to accept and store `level`, `children`, `parent` fields in frontmatter. Default `level` to 1. When called inside a thinker context (TRAJ_ID is set), auto-populate `children` with recent step-ids and `source_range`/`source_traj` from the current traj position.

Add `mem children <id>` — prints the children of an entry (resolving step-ids via `traj cat` and mem-ids via `mem show`).

Add `mem parent <id>` — prints the parent entry.

Backward compatible: existing mem files without these fields continue to work as unlinked level-1 entries.

### Phase 2: Bridge rollups ↔ mem

When `recap` seals a tier-1 block, check if any `mem add` calls happened during that step range (by scanning mem files' `source_range`). If so, add those mem ids to the rollup's entry as children, and patch those mem files' `parent` field to point to the rollup.

When the `learn` or `goals` monolith route creates a mem entry, the entry is linked to the episode covering its `source_range`.

### Phase 3: Drill-down skill

Create `skills/progressive-recall/SKILL.md` teaching the agent the top-down navigation pattern. Wire `mem children` and `mem parent` as the primitive operations.

### Phase 4: Replace `mem search` with hierarchical scan

Today `mem search` concatenates all memories and LLM-scans. Replace with: scan level-N summaries → drill relevant branches → return matches. Same interface, logarithmic cost.

### Phase 5: Cross-links (same-level neighbors)

Add optional `related` field to mem entries — links to other entries at the same level that are thematically connected. The `learn` route populates these when it notices recurring themes across episodes. This completes the HNSW analogy: each node has links up (parent), down (children), and sideways (related).

## Design consequences

### The mem file IS the node

No separate index database. The mem file's frontmatter is the node metadata (id, level, links); the body is the content. `mem list --level N` is just `ls + grep level: N` in the frontmatter. The filesystem is the graph store.

### Rollup entries become mem entries

Today rollups live in `recap/` as JSON. In unified mode, tier-1+ rollups are also written as mem files (type: `episode`) with the standard envelope. This means `mem search`, `mem children`, `mem parent` all work on episodes too — one tool, one namespace.

The JSON cache in `recap/` remains as the build cache; the mem file is the durable, navigable copy.

### Backward compatibility

Existing mem files are unlinked level-1 entries. Everything works; they just can't be drilled into or navigated hierarchically until someone (the `learn` route, a migration script, the agent itself) adds the link fields.

### Cost model

Drill-down: ~log_10(N) LLM calls to find a specific memory, each scanning ~10 summaries. For 10,000 memories: ~4 calls. For 1,000,000: ~6 calls.

Building links: marginal cost at write time (a few field additions). No retroactive reindexing needed for new entries.

## The 1:10:100 ratio in practice

The three-level pattern you noticed in mem files is the natural fanout:

```
  1 filename           → picks this entry from thousands    (~1 token)
 10 frontmatter words  → enough to decide relevance         (~10 tokens)
100 body words         → enough to act on the content       (~100 tokens)
```

This maps directly to the tiered rollup ratio:

```
  1 tier-2 rollup      → covers 100 raw steps              (~50 tokens)
 10 tier-1 rollups     → cover the same 100 steps at 10x   (~500 tokens)
100 raw steps          → full detail                        (~1000 tokens)
```

The ~10x compression at each level is what makes the hierarchy work: at each drill-down step, you're expanding ~10x in detail while reading ~10 entries. The total work to reach any point is ~10 × log_10(N) entries scanned.

## Open questions

1. **Fanout for semantic memories.** Episodic rollups have a natural fanout of 10 (10 steps → 1 rollup). Semantic memories don't — how many beliefs cluster into a theme? Probably variable. The drill-down skill handles variable fanout fine; the question is whether the `learn` route should explicitly target ~10 children per theme.

2. **When to create level-2+ semantic entries.** Tier-2 episodic rollups are created automatically when 10 tier-1 blocks seal. Semantic themes/arcs need an active decision ("these 8 beliefs form a pattern"). The `values_manager` or `goals_manager` thinker is the natural home; the trigger is "accumulated N unparented entries of this type."

3. **Same-level links: explicit or emergent?** Phase 5 adds `related` links. An alternative: don't store them, let the drill-down skill discover relatedness by scanning siblings under a shared parent. Simpler, but loses the HNSW "shortcut" property.
