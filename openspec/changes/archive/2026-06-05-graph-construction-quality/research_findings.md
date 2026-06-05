# Research Findings: Graph Construction Quality

## Executive Summary

The graph shows **good overall connectivity** (single connected component, no isolated nodes) thanks to seed_graph_bounding and fanout_reducer. However, **cross-document connectivity remains limited** (15.6% of edges), with **64.5% of nodes having only same-document connections**.

**Experiment Results:** Cross-document linking pass shows significant improvement potential:
- Cross-doc edges: 15.6% → 19.1% (+27.8% increase)
- Total edges: 9,976 → 10,408 (+432 edges, +4.3%)
- Average degree: 5.23 → 5.46 (+4.4%)

## Key Findings

### 1. Current Graph Metrics (multihop_chat_200_v2.db)

| Metric | Value |
|--------|-------|
| Nodes | 3,815 |
| Edges | 9,976 |
| Avg Degree | 5.23 |
| Connected Components | 1 (100% connected) |
| Isolated Nodes | 0 |
| Cross-Doc Edges | 1,555 (15.6%) |
| Nodes with only same-doc connections | 2,452 (64.5%) |

### 2. Why Cross-Document Connectivity is Limited

**Root Cause Analysis:**

1. **Stage 2 (Related Node Lookup)** uses the query engine to find related nodes based on the processed text. The query engine:
   - Relies on IndexInterface plugins (e.g., AliasIndex) to locate seeds
   - Seeds are matched by name/alias similarity to the text
   - This tends to find nodes from the **same domain/topic** but not necessarily different documents

2. **Stage 4 (judge_relations)** prompt explicitly says "宁可不合，不可错合" (prefer create over wrong merge):
   - This bias prevents false merges but also reduces cross-document connections
   - New concepts default to `create` with `edges_to` pointing to anchors from stage 2
   - If stage 2 returns mostly same-document anchors, cross-doc connections are rare

3. **Intra-document linking via `edges_to_names`**:
   - Provides good connectivity within the same document
   - But does nothing for cross-document connections

### 3. Improvement Opportunities

**High Priority:**
- **Enhance Stage 2 anchor recall**: Add a cross-document anchor retrieval step
- **Post-build cross-doc linking pass**: After all documents are ingested, run a pass to identify and connect related concepts across documents

**Medium Priority:**
- **CommunityMerger**: Implement community detection to create hub nodes that bridge document clusters
- **Adjust judge_relations prompt**: Slightly relax the "prefer create" bias for high-confidence matches

**Low Priority (Research Only):**
- **Directed/Typed edges**: Would enable more sophisticated traversal but requires significant refactoring

### 4. Comparison with Proposal Expectations

The proposal expected much worse metrics (based on older data without seed_graph_bounding):

| Metric | Proposal Expected | Actual | Improvement |
|--------|------------------|--------|-------------|
| Isolated Nodes | 34% | 0% | ✓ Fixed |
| Components | 1,681 | 1 | ✓ Fixed |
| Avg Degree | 1.32 | 5.23 | ✓ Improved |
| Cross-Doc Edges | 634 (22%) | 1,555 (15.6%) | ~ Same ratio |

The **primary remaining opportunity** is improving cross-document connectivity for better multi-hop reasoning.

## Recommendations

1. **Focus on cross-document linking** - This is the highest-impact improvement
2. **Implement diagnostic as regression baseline** - Ensure future changes can be measured
3. **Run controlled experiments** - Small-scale A/B tests on 50-100 docs before full implementation
4. **Consider ROI carefully** - The reranker already solves retrieval quality; cross-doc linking may have diminishing returns

## Next Steps

- [x] Implement cross-document anchor retrieval (Stage 2 enhancement)
- [x] Implement post-build cross-doc linking pass (with DB persistence)
- [x] Run controlled experiments with diagnostic comparison (cross-doc linking: 1,555 → 1,987 cross-doc edges; see `cross_doc_link_results.json`)
- [x] Decide on CommunityMerger: implemented + registered as opt-in CompactionPlugin, **disabled by default**; large-scale A/B deferred until evaluation shows hubs are needed

## Experiment Results: Cross-Document Linking Pass

### Strategy 1: Name Match
- **Candidates found:** 407
- **Mechanism:** Find nodes with identical names across different documents
- **Confidence:** 1.0 (exact match)

### Strategy 2: Alias Match
- **Candidates found:** 25
- **Mechanism:** Find nodes whose aliases match other nodes' names across documents
- **Confidence:** 0.8 (alias-to-name match)

### Combined Results

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Nodes | 3,815 | 3,815 | - |
| Edges | 9,976 | 10,408 | +432 (+4.3%) |
| Avg Degree | 5.23 | 5.46 | +0.23 (+4.4%) |
| Cross-Doc Edges | 1,555 (15.6%) | 1,987 (19.1%) | +432 (+27.8%) |
| Connected Components | 1 | 1 | - |

### Key Insight
The cross-doc linking pass is a **zero-cost improvement** (no LLM calls needed) that significantly increases cross-document connectivity. Name matching alone finds 407 candidates — suggesting that many same-named concepts across documents are currently disconnected.

## Research: Directed/Typed Edges

### Current State
- Edges have a `direction` field ("bidirectional" | "out") but it's only used by fanout_reducer for community reorganization
- Edges have no semantic type/label (e.g., "is_a", "part_of", "causes")
- `GraphStore._adjacency` is symmetric — treats all edges as undirected for neighbor queries

### Potential Benefits of Typed/Directed Edges
1. **Better multi-hop traversal**: Query engine could follow specific relation types instead of BFS
2. **More precise `decide_directions`**: LLM could select edges by semantic meaning
3. **Support for hierarchical reasoning**: "is_a" / "part_of" edges enable inheritance

### Implementation Costs
1. **Edge schema change**: Add `relation_type: str` field to Edge dataclass
2. **judge_relations prompt update**: Ask LLM to classify edge types (adds token cost)
3. **Query engine changes**: `decide_directions` needs to reason about edge semantics
4. **Adjacency index changes**: Need to support directed traversal in `_adjacency`
5. **Storage changes**: SQLite schema already supports `direction` but needs `relation_type` column
6. **Backward compatibility**: Existing graphs have no relation types

### Recommendation
**Defer to a future change.** The cost-benefit ratio is unfavorable for this change:
- The cross-doc linking pass already provides a low-cost improvement
- The reranker already compensates for graph traversal limitations
- Adding edge types would touch nearly every core module (graph.py, write_pipeline.py, query_engine.py, judge_relations.py, storage)
- The investment would be better spent after validating that cross-doc linking improves multi-hop metrics

This should be a **separate change** if future evaluation shows that typed edges would provide significant additional benefit over cross-doc linking alone.
