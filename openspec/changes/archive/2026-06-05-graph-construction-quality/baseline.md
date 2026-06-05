# Graph Quality Baseline Report

**Generated:** 2026-06-05

**Database:** `multihop_chat_200_v2.db` (200 documents, MultiHop-RAG corpus)

## Summary Metrics

| Metric | Value |
|--------|-------|
| Nodes | 3,815 |
| Edges | 9,976 |
| Average Degree | 5.23 |
| Isolated Nodes | 0 (0.0%) |
| Connected Components | 1 |
| Largest Component | 3,815 nodes (100.0%) |
| Cross-Doc Edges | 1,555 (15.6%) |

## Node Role Distribution

| Role | Count | Percentage |
|------|-------|------------|
| concept | 3,799 | 99.6% |
| hub | 16 | 0.4% |

## Analysis

**Good News:** The current graph shows significantly better connectivity than initially expected in the proposal (which referenced older diagnostics showing 34% isolated nodes, 1681 components, and average degree 1.32).

**Improvements Already Applied:**
1. **Seed graph bounding** - Creates a virtual root connecting all seed nodes, ensuring single connected component
2. **Fanout reducer** - Creates hub nodes that help organize the graph
3. **Reranker** - Improves retrieval quality (though this doesn't affect graph structure)

**Remaining Concerns:**
1. **Cross-document connectivity (15.6%)** - Still relatively low, could be improved for multi-hop reasoning
2. **Node role imbalance** - Only 16 hub nodes for 3,815 concepts (0.4%), suggesting limited hierarchical organization

## Comparison with Proposal Expectations

| Metric | Proposal Expected | Actual | Change |
|--------|------------------|--------|--------|
| Nodes | ~4,380 | 3,815 | -13% |
| Edges | ~2,901 | 9,976 | +244% |
| Avg Degree | ~1.32 | 5.23 | +296% |
| Isolated Nodes | 34% | 0% | -100% |
| Components | 1,681 | 1 | -99.9% |
| Cross-Doc Edges | 634 | 1,555 | +145% |

**Conclusion:** The graph quality has already been substantially improved through seed_graph_bounding and fanout_reducer. The primary remaining opportunity is increasing cross-document connectivity for better multi-hop reasoning.
