"""Core engine - stable graph operations and pipeline state machines.

Contains:
  - ``mcs``: MCS top-level orchestrator with dual PluginManager architecture
  - ``builder``: MCSBuilder abstract base class for building MCS instances
  - ``config``: MCSConfig with shared/write/read plugin separation
  - ``graph``: Node/Edge dataclasses and GraphStore
  - ``decisions``: Decision/DecisionList dataclasses for write pipeline
  - ``errors``: Exception hierarchy
  - ``plugin``: Plugin base class and PluginType enum
  - ``plugin_manager``: PluginManager and PluginContext
  - ``query_engine``: QueryEngine for read pipeline
  - ``store``: StoreInterface ABC
  - ``token_budget``: TokenBudget
  - ``write_pipeline``: WritePipeline for ingest pipeline
  - ``context_renderer``: ContextRenderer for LLM input rendering

See architecture.md §2.
"""
